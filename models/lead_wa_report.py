# -*- coding: utf-8 -*-
"""Daily leads report to the director / team leads on WhatsApp (Meta WhatsApp Cloud API).

Meta only allows a business to start a chat with an APPROVED TEMPLATE. So the report goes as a template with
two variables ({{1}} = date, {{2}} = the report in one line, parts separated by ' | '). If no template name is
set the report is sent as normal text, which Meta delivers only to numbers that wrote to the business number
in the last 24 hours."""
import logging
import re
from datetime import timedelta

import pytz
import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

P = 'custom_leads_19.wa_report_'
GRAPH = 'https://graph.facebook.com/v21.0/%s/messages'
BUCKETS = [(0.25, '15 min'), (0.5, '30 min'), (1.0, '1 hr'), (2.0, '2 hr')]


class ResConfigSettingsWaReport(models.TransientModel):
    _inherit = 'res.config.settings'

    wa_report_enabled = fields.Boolean(string='Send the daily report on WhatsApp', config_parameter=P + 'enabled')
    wa_report_phone_id = fields.Char(string='Phone number ID', config_parameter=P + 'phone_id',
                                     help='WhatsApp Business number id from Meta (WhatsApp > API setup).')
    wa_report_token = fields.Char(string='Access token', config_parameter=P + 'token',
                                  help='Permanent token of the Meta system user.')
    wa_report_to = fields.Char(string='Send to (numbers)', config_parameter=P + 'to',
                               help='Director / team lead numbers with country code, separated by comma. '
                                    'Example: 919995551234, 919446667890')
    wa_report_template = fields.Char(string='Template name', config_parameter=P + 'template',
                                     help='Approved Utility template with two variables, for example: '
                                          '"Daily lead report for {{1}}: {{2}}". Empty = plain text '
                                          '(only reaches numbers that messaged you in the last 24 hours).')
    wa_report_lang = fields.Char(string='Template language', config_parameter=P + 'lang', default='en')
    wa_report_hour = fields.Integer(string='Send at (hour, 24h India time)', config_parameter=P + 'hour', default=19)

    def action_wa_report_test(self):
        self.execute()
        res = self.env['leads.logic'].send_wa_report(force=True)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('WhatsApp report'), 'message': res, 'type': 'info', 'sticky': True}}


class LeadsLogicWaReport(models.Model):
    _inherit = 'leads.logic'

    @api.model
    def _wa_report_data(self):
        R = self.with_context(tz=self._rd_tzname())
        today = str(fields.Date.context_today(R))
        s, e = self._rd_utc(today), self._rd_utc(today, end=True)
        dom = [('create_date', '>=', s), ('create_date', '<', e)]
        created = self.search_count(dom)
        assigned = self.search_count(dom + [('first_assigned_dt', '!=', False)])
        called = {}
        for hrs, label in BUCKETS:
            called[label] = self.search_count(dom + [('first_called_dt', '!=', False),
                                                     ('call_delay_hrs', '<=', hrs)])
        called_any = self.search_count(dom + [('first_called_dt', '!=', False)])
        rnr = len(self.env['lead.quality.history'].sudo()._read_group(
            [('lead_quality', '=', 'not_responding'), ('change_date', '>=', s), ('change_date', '<', e)],
            ['lead_id'], ['__count']))
        sm = self.sudo()._summary_data()
        officers = [o for o in sm['officers'] if o['calls'] or o['adm']]
        officers.sort(key=lambda o: (-o['adm'], -o['connected'], -o['calls']))
        return {'date': today, 'created': created, 'assigned': assigned, 'called': called,
                'not_called': created - called_any, 'rnr': rnr, 'officers': officers,
                'calls': sm['calls'], 'connected': sm['connected'], 'admissions': sm['admissions']}

    @api.model
    def _wa_report_text(self, d, flat=False):
        top = d['officers'][:3]
        adm_by = ', '.join('%s %s' % (o['name'], o['adm']) for o in d['officers'] if o['adm'])
        parts = [
            'New leads %s, assigned %s%s' % (d['created'], d['assigned'],
                                             (' (%s waiting)' % (d['created'] - d['assigned']))
                                             if d['created'] > d['assigned'] else ''),
            'Called within ' + ', '.join('%s: %s' % (k, v) for k, v in d['called'].items())
            + ', not called yet: %s' % d['not_called'],
            'RNR today %s' % d['rnr'],
            'Calls %s (connected %s)' % (d['calls'], d['connected']),
            'Top performers ' + ('; '.join('%s - %s calls, %s connected, %s admission' % (
                o['name'], o['calls'], o['connected'], o['adm']) for o in top) or 'none'),
            'Admissions today %s%s' % (d['admissions'], (' (%s)' % adm_by) if adm_by else ''),
        ]
        if flat:
            return ' | '.join(parts)[:900]
        icons = ['🆕', '⏱', '🔁', '📞', '🏆', '🎓']
        return '📊 *Leads report - %s*\n' % d['date'] + '\n'.join('%s %s' % (i, p) for i, p in zip(icons, parts))

    @staticmethod
    def _wa_number(n):
        n = re.sub(r'\D', '', n or '')
        return ('91' + n) if len(n) == 10 else n

    @api.model
    def _wa_send(self, to, text, flat, date, icp):
        phone_id, token = icp.get_param(P + 'phone_id'), icp.get_param(P + 'token')
        tpl = (icp.get_param(P + 'template') or '').strip()
        if tpl:
            body = {'messaging_product': 'whatsapp', 'to': to, 'type': 'template', 'template': {
                'name': tpl, 'language': {'code': icp.get_param(P + 'lang') or 'en'},
                'components': [{'type': 'body', 'parameters': [
                    {'type': 'text', 'text': date}, {'type': 'text', 'text': flat}]}]}}
        else:
            body = {'messaging_product': 'whatsapp', 'to': to, 'type': 'text', 'text': {'body': text[:4000]}}
        r = requests.post(GRAPH % phone_id, headers={'Authorization': 'Bearer ' + token}, json=body, timeout=30)
        if r.status_code >= 300:
            try:
                msg = r.json().get('error', {}).get('message', r.text)
            except ValueError:
                msg = r.text
            raise UserError('%s: %s' % (r.status_code, str(msg)[:200]))

    @api.model
    def send_wa_report(self, force=False):
        """Send today's report. Returns a short result text."""
        icp = self.env['ir.config_parameter'].sudo()
        if not force and icp.get_param(P + 'enabled') not in ('True', '1', 'true'):
            return ''
        if not (icp.get_param(P + 'phone_id') and icp.get_param(P + 'token') and icp.get_param(P + 'to')):
            return _('Fill Phone number ID, Access token and Send to in Settings first.')
        d = self.sudo()._wa_report_data()
        text, flat = self._wa_report_text(d), self._wa_report_text(d, flat=True)
        ok, bad = 0, []
        for raw in re.split(r'[,;\s]+', icp.get_param(P + 'to') or ''):
            num = self._wa_number(raw)
            if not num:
                continue
            try:
                self._wa_send(num, text, flat, d['date'], icp)
                ok += 1
            except Exception as ex:  # noqa: BLE001
                bad.append('%s: %s' % (num, str(ex)[:150]))
                _logger.warning('WhatsApp report to %s failed: %s', num, ex)
        if not force:
            icp.set_param(P + 'last_sent', d['date'])
        return _('Sent to %s number(s).') % ok + ((' ' + _('Failed:') + ' ' + '; '.join(bad)) if bad else '')

    @api.model
    def cron_wa_report(self):
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param(P + 'enabled') not in ('True', '1', 'true'):
            return
        tz = pytz.timezone(self._rd_tzname())
        now = pytz.utc.localize(fields.Datetime.now()).astimezone(tz)
        if now.hour < int(icp.get_param(P + 'hour') or 19) or icp.get_param(P + 'last_sent') == str(now.date()):
            return
        self.send_wa_report()
