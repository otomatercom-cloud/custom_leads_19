# -*- coding: utf-8 -*-
"""Management report templates: the manager writes the message with {placeholders}, picks the send time, the
days, the channel (Telegram / WhatsApp) and who receives it."""
import logging
import re
from html import escape

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .telegram_notify import P_TOKEN, tg_call

_logger = logging.getLogger(__name__)
WINDOW = 2          # sent at most this many hours after the set time
WA_P = 'custom_leads_19.wa_report_'

PLACEHOLDERS = [
    ('date', 'Today date'), ('created', 'Leads created today'), ('created_meta', 'Meta leads today'),
    ('yesterday', 'Leads yesterday'), ('yesterday_meta', 'Meta leads yesterday'),
    ('sources', 'Top sources today'), ('assigned', 'Leads assigned today'),
    ('called_15', 'First call within 15 min'), ('called_30', 'within 30 min'), ('called_1hr', 'within 1 hr'),
    ('called_2hr', 'within 2 hr'), ('not_called', 'Not called yet'), ('rnr', 'RNR leads today'),
    ('calls', 'Calls today'), ('connected', 'Connected calls today'), ('admissions', 'Admissions today'),
    ('top3', 'Top 3 officers'), ('present', 'Officers present'), ('total', 'Officers total'),
    ('on_time', 'On time list'), ('late', 'Late list'), ('absent', 'Not signed in list'),
    ('leave', 'On leave list')]


class LeadReportTemplate(models.Model):
    _name = 'lead.report.template'
    _description = 'Management report template'
    _order = 'send_time, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    channel = fields.Selection([('telegram', 'Telegram'), ('whatsapp', 'WhatsApp'), ('both', 'Telegram + WhatsApp')],
                               default='telegram', required=True)
    send_time = fields.Float(string='Send at', default=19.0, help='24h India time, e.g. 19:00.')
    mon = fields.Boolean('Mon', default=True)
    tue = fields.Boolean('Tue', default=True)
    wed = fields.Boolean('Wed', default=True)
    thu = fields.Boolean('Thu', default=True)
    fri = fields.Boolean('Fri', default=True)
    sat = fields.Boolean('Sat', default=True)
    sun = fields.Boolean('Sun', default=False)
    recipient_type = fields.Selection(
        [('managers', 'Managers, super admins and team leads'), ('selected', 'Only the users I pick')],
        default='managers', required=True)
    user_ids = fields.Many2many('res.users', string='Users')
    extra_numbers = fields.Char(string='Extra WhatsApp numbers',
                                help='Directors etc. with country code, comma separated: 919995551234, 919446667890')
    body = fields.Text(required=True, string='Message', default='Leads report - {date}\n'
                       'Created: {created} (Meta {created_meta})\nCalls: {calls}, connected {connected}\n'
                       'Admissions: {admissions}')
    placeholder_help = fields.Text(compute='_compute_placeholder_help')
    last_sent = fields.Date(readonly=True, copy=False)
    last_result = fields.Char(readonly=True, copy=False)

    @api.depends('name')
    def _compute_placeholder_help(self):
        txt = '\n'.join('{%s}  =  %s' % (k, v) for k, v in PLACEHOLDERS)
        for r in self:
            r.placeholder_help = txt

    # ------------------------------------------------------------------ data & rendering
    @api.model
    def _data(self):
        Lead = self.env['leads.logic'].sudo()
        L, A, d = Lead._tgrep_leads(), Lead._tgrep_attendance(), Lead._wa_report_data()
        c = d['called']
        top = ['%s. %s - %s calls, %s connected, %s adm' % (i, o['name'], o['calls'], o['connected'], o['adm'])
               for i, o in enumerate(d['officers'][:3], 1)]
        lst = lambda x: ', '.join(x) if x else '-'   # noqa: E731
        return {
            'date': d['date'], 'created': L['today'], 'created_meta': L['today_meta'], 'yesterday': L['yest'],
            'yesterday_meta': L['yest_meta'], 'sources': ', '.join('%s %s' % (n, k) for n, k in L['sources']) or '-',
            'assigned': d['assigned'], 'called_15': c.get('15 min', 0), 'called_30': c.get('30 min', 0),
            'called_1hr': c.get('1 hr', 0), 'called_2hr': c.get('2 hr', 0), 'not_called': d['not_called'],
            'rnr': d['rnr'], 'calls': d['calls'], 'connected': d['connected'], 'admissions': d['admissions'],
            'top3': '\n'.join(top) or '-', 'present': A['present'], 'total': A['total'],
            'on_time': lst(A['on_time']), 'late': lst(A['late']), 'absent': lst(A['absent']),
            'leave': lst(A['leave'])}

    def _render(self, data, html=False):
        self.ensure_one()
        body = escape(self.body) if html else self.body

        def sub(m):
            k = m.group(1)
            if k not in data:
                return m.group(0)
            v = escape(str(data[k])) if html else str(data[k])
            return ('<b>%s</b>' % v) if html else v
        return re.sub(r'\{(\w+)\}', sub, body)

    # ------------------------------------------------------------------ recipients
    def _users(self):
        self.ensure_one()
        if self.recipient_type == 'selected':
            return self.user_ids
        return self.env['leads.logic']._tgrep_users()

    @staticmethod
    def _user_number(u):
        emp = u.employee_id if 'employee_id' in u._fields else False
        p = u.partner_id
        return (emp and emp.mobile_phone) or (p._fields.get('mobile') and p.mobile) or p.phone or ''

    # ------------------------------------------------------------------ sending
    def _send(self, only_user=None):
        """Returns a short result text."""
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        data = self._data()
        res, users = [], (only_user or self._users())
        if self.channel in ('telegram', 'both'):
            token = icp.get_param(P_TOKEN)
            if not token:
                res.append(_('Telegram: bot token missing.'))
            else:
                html, ok = self._render(data, html=True)[:4000], 0
                missing = users.filtered(lambda u: not u.telegram_chat_id)
                for u in users.filtered('telegram_chat_id'):
                    r = tg_call(token, 'sendMessage', {'chat_id': u.telegram_chat_id, 'parse_mode': 'HTML',
                                                       'text': html})
                    ok += 1 if r.get('ok') else 0
                res.append(_('Telegram %s') % ok + (' (' + _('no Chat ID') + ': ' + ', '.join(missing.mapped('name'))
                                                    + ')' if missing else ''))
        if self.channel in ('whatsapp', 'both'):
            wa = self.env['leads.logic'].sudo()
            if not (icp.get_param(WA_P + 'phone_id') and icp.get_param(WA_P + 'token')):
                res.append(_('WhatsApp: fill the Cloud API details in Settings.'))
            else:
                nums = [wa._wa_number(self._user_number(u)) for u in users]
                if not only_user:
                    nums += [wa._wa_number(x) for x in re.split(r'[,;\s]+', self.extra_numbers or '')]
                text = self._render(data)
                flat = re.sub(r'\s*\n+\s*', ' | ', text.strip())
                ok, bad = 0, 0
                for n in dict.fromkeys(x for x in nums if x):
                    try:
                        wa._wa_send(n, text, flat, data['date'], icp)
                        ok += 1
                    except Exception as ex:  # noqa: BLE001
                        bad += 1
                        _logger.warning('Report template %s: WhatsApp to %s failed: %s', self.name, n, ex)
                res.append(_('WhatsApp %s') % ok + (' (%s %s)' % (bad, _('failed')) if bad else ''))
        return ', '.join(res)

    def action_send_now(self):
        self.ensure_one()
        msg = self._send()
        self.write({'last_result': msg})
        return self._notify(msg)

    def action_send_test(self):
        self.ensure_one()
        if not self.env.user.telegram_chat_id and self.channel != 'whatsapp':
            raise UserError(_('Set your Telegram Chat ID on your user first.'))
        return self._notify(self._send(only_user=self.env.user))

    def _notify(self, msg):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': self.name, 'message': msg, 'type': 'info', 'sticky': True}}

    @api.model
    def cron_send_templates(self):
        local = pytz.utc.localize(fields.Datetime.now()).astimezone(pytz.timezone(
            self.env['leads.logic']._rd_tzname()))
        today, now_f = local.date(), local.hour + local.minute / 60.0
        day = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][local.weekday()]
        for t in self.search([('active', '=', True)]):
            if not t[day] or t.last_sent == today or not (t.send_time <= now_f < t.send_time + WINDOW):
                continue
            t.last_sent = today                       # mark first: never send twice
            try:
                t.last_result = t._send()
                self.env.cr.commit()
            except Exception:  # noqa: BLE001
                _logger.exception('Report template %s failed', t.name)
