# -*- coding: utf-8 -*-
"""Evening summary for managers by Telegram and/or email."""
import logging
from datetime import timedelta
from html import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .telegram_notify import P_TOKEN, tg_call

_logger = logging.getLogger(__name__)

P_ON = 'custom_leads_19.daily_summary_enabled'
P_TG = 'custom_leads_19.daily_summary_telegram'
P_MAIL = 'custom_leads_19.daily_summary_email'
MAX_OFFICERS = 40


class ResConfigSettingsDailySummary(models.TransientModel):
    _inherit = 'res.config.settings'

    daily_summary_enabled = fields.Boolean(string='Send the evening summary', config_parameter=P_ON)
    daily_summary_telegram = fields.Boolean(string='By Telegram', config_parameter=P_TG, default=True)
    daily_summary_email = fields.Boolean(string='By email', config_parameter=P_MAIL)

    def action_daily_summary_test(self):
        self.execute()
        self.env['leads.logic'].send_daily_summary(only_user=self.env.user, force=True)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Evening summary'), 'message': _('Sent to you. Check Telegram / email.'),
                           'type': 'success'}}


class LeadsLogicDailySummary(models.Model):
    _inherit = 'leads.logic'

    @api.model
    def _summary_data(self):
        """Today's numbers (local day)."""
        R = self.env['otm.lead.reports'].with_context(tz=self._rd_tzname())
        today = str(fields.Date.context_today(R))
        f = {'date_from': today, 'date_to': today}
        s, e = self._rd_utc(today), self._rd_utc(today, end=True)
        now = fields.Datetime.now()
        card = R._r_officer_scorecard(f)
        adm = {}
        for emp, n in self._read_group([('admission_status', '=', True), ('admission_date', '>=', s),
                                        ('admission_date', '<', e)], ['lead_owner'], ['__count']):
            adm[emp.name if emp else '(none)'] = n
        names = {r['name'] for r in card['rows']} | set(adm)
        officers = []
        for n in names:
            r = next((x for x in card['rows'] if x['name'] == n), {})
            officers.append({'name': n, 'calls': r.get('calls', 0), 'connected': r.get('connected', 0),
                             'secs': r.get('secs', 0), 'fover': r.get('fover', 0), 'adm': adm.get(n, 0)})
        officers.sort(key=lambda x: (-x['adm'], -x['calls']))
        return {
            'date': today,
            'new': self.search_count([('create_date', '>=', s), ('create_date', '<', e)]),
            'calls': card['totals'].get('calls', 0), 'connected': card['totals'].get('connected', 0),
            'secs': card['totals'].get('secs', 0),
            'uncalled_today': self.search_count([('create_date', '>=', s), ('create_date', '<', e),
                                                 ('first_called_dt', '=', False), ('state', '!=', 'lost')]),
            'unassigned': self.search_count([('lead_owner', '=', False), ('state', '!=', 'lost'),
                                             ('create_date', '>=', now - timedelta(days=7))]),
            'missed_fu': self.env['lead.followup'].search_count([('status', '=', 'scheduled'),
                                                                 ('next_followup_date', '<', now)]),
            'admissions': sum(adm.values()), 'officers': officers,
        }

    @staticmethod
    def _fmt_secs(secs):
        h, m = int(secs // 3600), int(secs % 3600 // 60)
        return '%sh %02dm' % (h, m) if h else '%sm' % m

    @api.model
    def _summary_html(self, d):
        b = lambda v: '<b>%s</b>' % escape(str(v))  # noqa: E731
        lines = [
            '📊 %s - %s' % (b(_('Leads summary')), escape(d['date'])), '',
            '🆕 ' + _('New leads') + ': ' + b(d['new']),
            '📞 ' + _('Calls') + ': ' + b(d['calls']) + ' (' + _('connected') + ' ' + str(d['connected']) + ', '
            + _('talk time') + ' ' + self._fmt_secs(d['secs']) + ')',
            '⏳ ' + _('New leads not called yet') + ': ' + b(d['uncalled_today']),
            '📥 ' + _('Waiting for an officer') + ': ' + b(d['unassigned']),
            '⚠️ ' + _('Missed follow-ups') + ': ' + b(d['missed_fu']),
            '🎓 ' + _('Admissions today') + ': ' + b(d['admissions']), '',
            b(_('By officer')) + ' (' + _('calls / connected / overdue follow-ups / admissions') + ')',
        ]
        for o in d['officers'][:MAX_OFFICERS]:
            lines.append('%s: %s / %s / %s / %s' % (escape(o['name']), o['calls'], o['connected'], o['fover'], o['adm']))
        if len(d['officers']) > MAX_OFFICERS:
            lines.append('... +%s' % (len(d['officers']) - MAX_OFFICERS))
        return '\n'.join(lines)

    @api.model
    def send_daily_summary(self, only_user=None, force=False):
        icp = self.env['ir.config_parameter'].sudo()
        on = lambda p, d='False': icp.get_param(p, d) in ('True', '1', 'true')  # noqa: E731
        if not force and not on(P_ON):
            return 0
        users = only_user or self.env['res.users'].sudo().search([
            '|', ('group_ids', 'in', self.env.ref('custom_leads_19.group_lead_manager').ids),
            ('group_ids', 'in', self.env.ref('custom_leads_19.group_super_admin').ids)])
        data = self.sudo()._summary_data()
        html = self._summary_html(data)
        sent = 0
        token = icp.get_param(P_TOKEN)
        if (force or on(P_TG, 'True')) and token:
            for u in users.filtered('telegram_chat_id'):
                res = tg_call(token, 'sendMessage', {'chat_id': u.telegram_chat_id, 'parse_mode': 'HTML',
                                                     'text': html[:4000]})
                sent += 1 if res.get('ok') else 0
        if force or on(P_MAIL):
            for u in users.filtered('email'):
                self.env['mail.mail'].sudo().create({
                    'subject': _('Leads summary - %s') % data['date'], 'email_to': u.email,
                    'body_html': '<div>%s</div>' % html.replace('\n', '<br/>'),
                    'author_id': self.env.company.partner_id.id,
                }).send()
                sent += 1
        return sent
