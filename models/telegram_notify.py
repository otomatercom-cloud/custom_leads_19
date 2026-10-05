"""Telegram alerts for Lead follow-ups (Admission Officers).

* instant message when a follow-up is scheduled for an officer
* reminder N minutes before the follow-up is due (cron, every 5 min)
* overdue alert (30 min after due time, still 'scheduled')
* morning digest with today's follow-ups per officer (cron, daily 9:00 IST)

Telegram failures never block Odoo: they are logged and skipped.
"""
import logging
from datetime import timedelta
from html import escape

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

P_TOKEN = 'custom_leads_19.telegram_bot_token'
P_ENABLED = 'custom_leads_19.telegram_enabled'
P_MINUTES = 'custom_leads_19.telegram_reminder_minutes'
P_DIGEST = 'custom_leads_19.telegram_digest'
API = 'https://api.telegram.org/bot%s/%s'


def tg_call(token, method, payload=None, timeout=10):
    """Plain HTTP call (no ORM) - safe to use from a post-commit hook."""
    try:
        resp = requests.post(API % (token, method), json=payload or {}, timeout=timeout)
        data = resp.json()
        if not data.get('ok'):
            _logger.warning('Telegram %s failed: %s', method, data.get('description'))
        return data
    except Exception as exc:  # network, JSON, ...
        _logger.warning('Telegram %s error: %s', method, exc)
        return {'ok': False, 'description': str(exc)}


class ResUsers(models.Model):
    _inherit = 'res.users'

    telegram_chat_id = fields.Char(string='Telegram Chat ID', copy=False)
    telegram_username = fields.Char(string='Telegram Username', copy=False,
                                    help='Without @. Used only by "Find my Chat ID".')
    telegram_notify = fields.Boolean(string='Telegram Follow-Up Alerts', default=True)

    def action_send_test_telegram(self):
        self.ensure_one()
        token = self.env['ir.config_parameter'].sudo().get_param(P_TOKEN)
        if not token:
            raise UserError(_('Set the Telegram Bot Token in Settings > Leads first.'))
        if not self.telegram_chat_id:
            raise UserError(_('Enter the Telegram Chat ID (or use "Find my Chat ID") first.'))
        res = tg_call(token, 'sendMessage', {
            'chat_id': self.telegram_chat_id, 'parse_mode': 'HTML',
            'text': '✅ <b>%s</b>, Telegram alerts are connected for Leads follow-ups.' % escape(self.name)})
        if not res.get('ok'):
            raise UserError(_('Telegram said: %s') % res.get('description'))
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Telegram'), 'message': _('Test message sent.'),
                           'type': 'success'}}

    def action_find_telegram_chat_id(self):
        """Officer must first send any message to the bot; we read it via getUpdates."""
        self.ensure_one()
        token = self.env['ir.config_parameter'].sudo().get_param(P_TOKEN)
        if not token:
            raise UserError(_('Set the Telegram Bot Token in Settings > Leads first.'))
        uname = (self.telegram_username or '').strip().lstrip('@').lower()
        if not uname:
            raise UserError(_('Enter the Telegram Username first.'))
        data = tg_call(token, 'getUpdates', {'limit': 100})
        if not data.get('ok'):
            raise UserError(_('Telegram said: %s (if a webhook is set on this bot, use the '
                              'bot only for Leads or type the Chat ID manually)') % data.get('description'))
        for upd in reversed(data.get('result', [])):
            chat = (upd.get('message') or {}).get('chat') or {}
            if (chat.get('username') or '').lower() == uname and chat.get('id'):
                self.telegram_chat_id = str(chat['id'])
                return self.action_send_test_telegram()
        raise UserError(_('No message from @%s found. Ask the officer to open the bot in Telegram, '
                          'press Start and send "hi", then try again.') % uname)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    telegram_enabled = fields.Boolean(string='Enable Telegram Follow-Up Alerts', config_parameter=P_ENABLED)
    telegram_bot_token = fields.Char(string='Telegram Bot Token', config_parameter=P_TOKEN)
    telegram_reminder_minutes = fields.Integer(
        string='Remind Before (minutes)', config_parameter=P_MINUTES, default=15)
    telegram_digest = fields.Boolean(string='Morning Digest (9:00)', config_parameter=P_DIGEST, default=True)

    def action_telegram_test_me(self):
        self.execute()
        return self.env.user.action_send_test_telegram()


class LeadFollowup(models.Model):
    _inherit = 'lead.followup'

    tg_reminded = fields.Boolean(copy=False, default=False)
    tg_overdue_sent = fields.Boolean(copy=False, default=False)

    # ------------------------------------------------------------------ helpers
    @api.model
    def _tg_config(self):
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param(P_ENABLED) not in ('True', '1', 'true') or not icp.get_param(P_TOKEN):
            return None
        return {'token': icp.get_param(P_TOKEN),
                'minutes': int(icp.get_param(P_MINUTES) or 15),
                'digest': icp.get_param(P_DIGEST, 'True') in ('True', '1', 'true'),
                'base': icp.get_param('web.base.url', '')}

    def _tg_recipient(self):
        self.ensure_one()
        user = self.user_id
        if not (user and user.telegram_chat_id):
            user = self.lead_id.lead_owner.user_id if self.lead_id.lead_owner else self.env['res.users']
        if user and user.telegram_chat_id and user.telegram_notify:
            return user
        return self.env['res.users']

    def _tg_line(self, base, with_remarks=True):
        self.ensure_one()
        lead = self.lead_id
        when = fields.Datetime.context_timestamp(self.with_context(tz=self._tg_tz()), self.next_followup_date)
        phone = self.phone_number or lead.phone_number or ''
        link = '%s/web#id=%s&model=leads.logic&view_type=form' % (base, lead.id) if base else ''
        txt = '👤 <b>%s</b>  📞 %s\n🕒 %s' % (escape(lead.name or ''), escape(phone), when.strftime('%d %b %H:%M'))
        if with_remarks and self.remarks:
            txt += '\n📝 ' + escape(self.remarks[:200])
        if link:
            txt += '\n<a href="%s">Open lead</a>' % escape(link, quote=True)
        return txt

    def _tg_tz(self):
        return self.user_id.tz or self.env.user.tz or 'Asia/Kolkata'

    # ----------------------------------------------------------- instant alert
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        ctx = self.env.context
        if ctx.get('otm_odoo17_import') or ctx.get('otm_demo_load'):
            return records
        cfg = self._tg_config()
        if cfg:
            jobs = []
            for rec in records:
                user = rec._tg_recipient()
                if user:
                    jobs.append((user.telegram_chat_id,
                                 '🆕 <b>New follow-up scheduled</b>\n' + rec._tg_line(cfg['base'])))
            if jobs:
                token = cfg['token']
                self.env.cr.postcommit.add(lambda: [self._tg_push(token, c, t) for c, t in jobs])
        return records

    @staticmethod
    def _tg_push(token, chat_id, text):
        return tg_call(token, 'sendMessage', {
            'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True})

    # -------------------------------------------------------------------- crons
    @api.model
    def _cron_telegram_followups(self):
        cfg = self._tg_config()
        if not cfg:
            return
        now = fields.Datetime.now()
        soon = self.search([
            ('status', '=', 'scheduled'), ('tg_reminded', '=', False),
            ('next_followup_date', '>=', now - timedelta(minutes=5)),
            ('next_followup_date', '<=', now + timedelta(minutes=cfg['minutes']))], limit=100)
        for rec in soon:
            user = rec._tg_recipient()
            if user and self._tg_push(cfg['token'], user.telegram_chat_id,
                                      '⏰ <b>Follow-up due soon</b>\n' + rec._tg_line(cfg['base'])).get('ok'):
                rec.tg_reminded = True
            elif not user:
                rec.tg_reminded = True      # nobody to notify - don't retry forever
        late = self.search([
            ('status', '=', 'scheduled'), ('tg_overdue_sent', '=', False),
            ('next_followup_date', '<', now - timedelta(minutes=30)),
            ('next_followup_date', '>', now - timedelta(days=2))], limit=100)
        for rec in late:
            user = rec._tg_recipient()
            if user and self._tg_push(cfg['token'], user.telegram_chat_id,
                                      '🚨 <b>Follow-up OVERDUE</b>\n' + rec._tg_line(cfg['base'])).get('ok'):
                rec.tg_overdue_sent = True
            elif not user:
                rec.tg_overdue_sent = True

    @api.model
    def _cron_telegram_digest(self):
        cfg = self._tg_config()
        if not cfg or not cfg['digest']:
            return
        now = fields.Datetime.now()
        users = self.env['res.users'].sudo().search([('telegram_chat_id', '!=', False), ('telegram_notify', '=', True)])
        for user in users:
            tz_today = fields.Datetime.context_timestamp(self.with_context(tz=user.tz or 'Asia/Kolkata'), now).date()
            recs = self.search([('status', '=', 'scheduled'), ('user_id', '=', user.id),
                                ('next_followup_date', '!=', False)], order='next_followup_date asc', limit=300)
            todays = recs.filtered(lambda r: fields.Datetime.context_timestamp(
                r.with_context(tz=user.tz or 'Asia/Kolkata'), r.next_followup_date).date() == tz_today)
            overdue = recs.filtered(lambda r: r.next_followup_date < now and r not in todays)
            if not todays and not overdue:
                continue
            lines = ['🌅 <b>Good morning %s</b>' % escape(user.name.split(' (')[0]),
                     "You have <b>%d</b> follow-up(s) today%s." % (
                         len(todays), (' and <b>%d</b> overdue' % len(overdue)) if overdue else '')]
            for r in todays[:15]:
                t = fields.Datetime.context_timestamp(r.with_context(tz=user.tz or 'Asia/Kolkata'), r.next_followup_date)
                lines.append('• %s – %s (%s)' % (t.strftime('%H:%M'), escape(r.lead_id.name or ''),
                                                 escape(r.phone_number or r.lead_id.phone_number or '')))
            if len(todays) > 15:
                lines.append('… and %d more' % (len(todays) - 15))
            self._tg_push(cfg['token'], user.telegram_chat_id, '\n'.join(lines))
