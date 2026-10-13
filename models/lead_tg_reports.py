# -*- coding: utf-8 -*-
"""Scheduled Telegram updates for managers: leads created (with Meta), officer attendance and, in the
evening, the full daily report. Morning / afternoon / evening at the hours set in Settings."""
import logging
from html import escape

import pytz

from odoo import _, api, fields, models

from .telegram_notify import P_TOKEN, tg_call

_logger = logging.getLogger(__name__)

P = 'custom_leads_19.tgrep_'
SLOTS = [('morning', 10, '🌅', 'Morning update'), ('afternoon', 14, '☀️', 'Afternoon update'),
         ('evening', 19, '🌆', 'Evening report')]
WINDOW = 2          # a slot is sent at most this many hours after its hour (server was off, etc.)


class ResConfigSettingsTgReports(models.TransientModel):
    _inherit = 'res.config.settings'

    tgrep_enabled = fields.Boolean(string='Telegram updates for managers', config_parameter=P + 'enabled')
    tgrep_morning = fields.Integer(string='Morning at (hour)', config_parameter=P + 'morning', default=10)
    tgrep_afternoon = fields.Integer(string='Afternoon at (hour)', config_parameter=P + 'afternoon', default=14)
    tgrep_evening = fields.Integer(string='Evening at (hour)', config_parameter=P + 'evening', default=19)
    tgrep_team_leads = fields.Boolean(string='Also send to team leads', config_parameter=P + 'team_leads')

    def action_tgrep_test(self):
        self.execute()
        n = self.env['leads.logic'].send_tg_report('evening', only_user=self.env.user, force=True)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Telegram'), 'type': 'success' if n else 'warning',
                           'message': _('Sent to you.') if n else _(
                               'Not sent. Check the bot token and your Telegram Chat ID.')}}


class LeadsLogicTgReports(models.Model):
    _inherit = 'leads.logic'

    @api.model
    def _tgrep_leads(self):
        today = str(fields.Date.context_today(self.with_context(tz=self._rd_tzname())))
        s, e = self._rd_utc(today), self._rd_utc(today, end=True)
        ys = self._rd_utc(fields.Date.subtract(fields.Date.to_date(today), days=1))
        meta = [('leads_source.name', 'ilike', 'meta')]
        d_today, d_yest = [('create_date', '>=', s), ('create_date', '<', e)], [('create_date', '>=', ys), ('create_date', '<', s)]
        by_src = [(src.name if src else _('(no source)'), n) for src, n in
                  self._read_group(d_today, ['leads_source'], ['__count'], order='__count desc', limit=5)]
        return {'today': self.search_count(d_today), 'today_meta': self.search_count(d_today + meta),
                'yest': self.search_count(d_yest), 'yest_meta': self.search_count(d_yest + meta),
                'sources': by_src}

    @api.model
    def _tgrep_attendance(self):
        members = self.env['lead.team.member'].sudo().search([('team_id.active', '=', True)])
        emps = members.mapped('employee_id').filtered(lambda e: e.user_id and e.user_id.active)
        today = fields.Date.context_today(self.with_context(tz=self._rd_tzname()))
        s, e = self._rd_utc(today), self._rd_utc(today, end=True)
        present, leave = set(), set()
        if 'hr.attendance' in self.env:
            present = set(self.env['hr.attendance'].sudo().search([
                ('employee_id', 'in', emps.ids), ('check_in', '>=', s), ('check_in', '<', e)]).mapped('employee_id').ids)
        if 'hr.leave' in self.env:
            try:
                leave = set(self.env['hr.leave'].sudo().search([
                    ('employee_id', 'in', emps.ids), ('state', '=', 'validate'),
                    ('date_from', '<', e), ('date_to', '>=', s)]).mapped('employee_id').ids)
            except Exception:  # noqa: BLE001
                _logger.exception('Leave lookup failed')
        absent = emps.filtered(lambda x: x.id not in present and x.id not in leave)
        return {'total': len(emps), 'present': len(present & set(emps.ids)),
                'absent': sorted(absent.mapped('name')),
                'leave': sorted(emps.filtered(lambda x: x.id in leave and x.id not in present).mapped('name'))}

    @api.model
    def _tgrep_html(self, slot):
        _slot, _h, icon, title = next(x for x in SLOTS if x[0] == slot)
        h = lambda v: '<b>%s</b>' % escape(str(v))  # noqa: E731
        L, A = self._tgrep_leads(), self._tgrep_attendance()
        date = fields.Date.context_today(self.with_context(tz=self._rd_tzname()))
        out = ['%s %s - %s' % (icon, h(_(title)), escape(date.strftime('%d %b %Y'))), '',
               '🆕 ' + _('Leads today so far') + ': ' + h(L['today']) + ' (Meta ' + h(L['today_meta']) + ')',
               '📅 ' + _('Leads yesterday') + ': ' + h(L['yest']) + ' (Meta ' + str(L['yest_meta']) + ')']
        if L['sources']:
            out.append('📌 ' + ', '.join('%s %s' % (escape(n), c) for n, c in L['sources']))
        out += ['', '👥 ' + _('Attendance') + ': ' + h('%s / %s' % (A['present'], A['total'])) + ' ' + _('present')]
        if A['absent']:
            out.append('❌ ' + _('Not signed in') + ': ' + escape(', '.join(A['absent'])))
        if A['leave']:
            out.append('🌴 ' + _('On leave') + ': ' + escape(', '.join(A['leave'])))
        if slot == 'evening':
            d = self.sudo()._wa_report_data()
            top = d['officers'][:3]
            out += ['',
                    '📥 ' + _('Assigned') + ': ' + h('%s / %s' % (d['assigned'], d['created'])),
                    '⏱ ' + _('First call within') + ': ' + ', '.join('%s %s' % (k, h(v)) for k, v in d['called'].items())
                    + ', ' + _('not called yet') + ' ' + h(d['not_called']),
                    '🔁 ' + _('RNR today') + ': ' + h(d['rnr']),
                    '📞 ' + _('Calls') + ': ' + h(d['calls']) + ' (' + _('connected') + ' ' + str(d['connected']) + ')']
            if top:
                out.append('🏆 ' + _('Top performers'))
                out += ['%s. %s - %s %s, %s %s, %s %s' % (
                    i, escape(o['name']), o['calls'], _('calls'), o['connected'], _('connected'), o['adm'],
                    _('admission')) for i, o in enumerate(top, 1)]
            out.append('🎓 ' + _('Admissions today') + ': ' + h(d['admissions']))
        return '\n'.join(out)

    @api.model
    def _tgrep_users(self):
        env = self.env
        groups = [env.ref('custom_leads_19.group_lead_manager').id, env.ref('custom_leads_19.group_super_admin').id]
        if env['ir.config_parameter'].sudo().get_param(P + 'team_leads') in ('True', '1', 'true'):
            groups.append(env.ref('custom_leads_19.group_lead_team_lead').id)
        return env['res.users'].sudo().search([('group_ids', 'in', groups)]).filtered('telegram_chat_id')

    @api.model
    def send_tg_report(self, slot, only_user=None, force=False):
        icp = self.env['ir.config_parameter'].sudo()
        token = icp.get_param(P_TOKEN)
        if not token or not (force or icp.get_param(P + 'enabled') in ('True', '1', 'true')):
            return 0
        text = self.sudo()._tgrep_html(slot)
        users = only_user or self._tgrep_users()
        sent = 0
        for u in users.filtered('telegram_chat_id'):
            res = tg_call(token, 'sendMessage', {'chat_id': u.telegram_chat_id, 'parse_mode': 'HTML',
                                                 'text': text[:4000]})
            sent += 1 if res.get('ok') else 0
        return sent

    @api.model
    def cron_tg_reports(self):
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param(P + 'enabled') not in ('True', '1', 'true'):
            return
        local = pytz.utc.localize(fields.Datetime.now()).astimezone(pytz.timezone(self._rd_tzname()))
        today = str(local.date())
        for slot, default, _i, _t in SLOTS:
            hour = int(icp.get_param(P + slot) or default)
            if not (hour <= local.hour < hour + WINDOW) or icp.get_param(P + 'sent_' + slot) == today:
                continue
            icp.set_param(P + 'sent_' + slot, today)          # mark first: never send twice
            try:
                n = self.send_tg_report(slot)
                _logger.info('Telegram %s update sent to %s user(s).', slot, n)
            except Exception:  # noqa: BLE001
                _logger.exception('Telegram %s update failed', slot)
