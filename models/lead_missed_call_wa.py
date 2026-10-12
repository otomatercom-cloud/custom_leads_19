# -*- coding: utf-8 -*-
"""WhatsApp message after a missed (not connected) outgoing call.

The trigger, template, rules and audit trail live here. The actual sending is done by whatever WhatsApp
module is installed: it only has to provide `leads.logic.otm_wa_send_text(text, officer)` and return
(True, '') or (False, 'reason'). Until then messages wait as 'Pending' and are sent when a sender exists."""
import logging
from datetime import timedelta

import pytz

from odoo import _, api, fields, models

from .call_report import _NOT_CONNECTED_KEYWORDS, _parse_duration_seconds

_logger = logging.getLogger(__name__)

P_ON = 'custom_leads_19.wa_missed_enabled'
P_TEXT = 'custom_leads_19.wa_missed_template'
P_FROM = 'custom_leads_19.wa_missed_from_hour'
P_TO = 'custom_leads_19.wa_missed_to_hour'
DEFAULT_TEXT = ("Hi {name}, this is {officer} from {institute}. I tried to call you about your enquiry "
                "for {course}. When is a good time to talk? You can reply here.")
NO_MESSAGE_QUALITY = ('admission', 'logic_students', 'joined_other_institute', 'wrong_number',
                      'not_enquiry', 'not_interested', 'bad_lead')


class ResConfigSettingsMissedWa(models.TransientModel):
    _inherit = 'res.config.settings'

    wa_missed_enabled = fields.Boolean(string='WhatsApp after a missed call', config_parameter=P_ON)
    wa_missed_template = fields.Char(string='Message', config_parameter=P_TEXT, default=DEFAULT_TEXT,
                                     help='Placeholders: {name} {officer} {course} {institute}')
    wa_missed_from_hour = fields.Integer(string='Send from (hour)', config_parameter=P_FROM, default=9)
    wa_missed_to_hour = fields.Integer(string='Send until (hour)', config_parameter=P_TO, default=19)


class LeadMissedCallWa(models.Model):
    _name = 'lead.missed.call.wa'
    _description = 'WhatsApp after missed call'
    _order = 'id desc'

    lead_id = fields.Many2one('leads.logic', required=True, ondelete='cascade', index=True)
    call_id = fields.Many2one('lead.call.log', ondelete='set null')
    officer_id = fields.Many2one('res.users', string='Officer')
    text = fields.Text(string='Message')
    state = fields.Selection([('pending', 'Pending'), ('sent', 'Sent'), ('skipped', 'Skipped'), ('failed', 'Failed')],
                             default='pending', index=True)
    note = fields.Char(string='Note')
    sent_date = fields.Datetime()

    # ───────────────────────── helpers ─────────────────────────────
    @api.model
    def _cfg(self):
        icp = self.env['ir.config_parameter'].sudo()
        return {
            'on': icp.get_param(P_ON) in ('True', '1', 'true'),
            'text': icp.get_param(P_TEXT) or DEFAULT_TEXT,
            'from': int(icp.get_param(P_FROM) or 9), 'to': int(icp.get_param(P_TO) or 19),
        }

    @api.model
    def _in_hours(self, cfg):
        tz = pytz.timezone(self.env['leads.logic']._rd_tzname())
        h = pytz.utc.localize(fields.Datetime.now()).astimezone(tz).hour
        return cfg['from'] <= h < cfg['to']

    @api.model
    def _build_text(self, lead, officer, tpl):
        course = lead.course_inter[:1].display_name if lead.course_inter else _('your course')
        vals = {'name': (lead.name or '').split(' ')[0] or _('there'), 'officer': officer.name or _('our team'),
                'course': course, 'institute': self.env.company.name or ''}
        try:
            return tpl.format(**vals)
        except (KeyError, IndexError, ValueError):
            return DEFAULT_TEXT.format(**vals)

    @api.model
    def handle_missed_call(self, call):
        """Queue (and try to send) one message for this call. Never raises."""
        try:
            cfg = self._cfg()
            if not cfg['on'] or not call.lead_id:
                return
            if call.call_type == 'incoming':
                return
            secs = _parse_duration_seconds(call.duration)
            status = (call.call_status or '').lower()
            if secs > 0 or not any(k in status for k in _NOT_CONNECTED_KEYWORDS):
                return  # only a clear "not answered / busy / failed" counts
            lead = call.lead_id.sudo()
            if lead.lead_quality in NO_MESSAGE_QUALITY or not lead.phone_number:
                return
            since = fields.Datetime.now() - timedelta(hours=24)
            if self.sudo().search_count([('lead_id', '=', lead.id), ('create_date', '>=', since),
                                         ('state', '!=', 'failed')]):
                return  # one message per lead per day
            officer = call.user_id or lead.lead_owner.user_id
            rec = self.sudo().create({
                'lead_id': lead.id, 'call_id': call.id, 'officer_id': officer.id,
                'text': self._build_text(lead, officer, cfg['text'])})
            if self._in_hours(cfg):
                rec._try_send()
            else:
                rec.note = _('Outside sending hours - will go at %s:00') % cfg['from']
        except Exception:  # noqa: BLE001 - a WhatsApp problem must never block call logging
            _logger.exception('Missed-call WhatsApp failed')

    def _try_send(self):
        for rec in self:
            lead = rec.lead_id.sudo()
            sender = getattr(lead, 'otm_wa_send_text', None)
            if not sender:
                rec.note = _('No WhatsApp sender module is connected yet')
                continue
            try:
                ok, why = sender(rec.text, rec.officer_id)
            except Exception as exc:  # noqa: BLE001
                ok, why = False, str(exc)[:200]
            if ok:
                rec.write({'state': 'sent', 'sent_date': fields.Datetime.now(), 'note': False})
                lead.message_post(body=_('WhatsApp sent after missed call: %s') % rec.text)
            else:
                rec.write({'state': 'failed', 'note': why or _('Sending failed')})

    @api.model
    def cron_send_pending(self):
        """Retry messages that waited for sending hours or for a sender module (only last 6 hours)."""
        cfg = self._cfg()
        if not cfg['on'] or not self._in_hours(cfg):
            return
        recs = self.sudo().search([('state', '=', 'pending'),
                                   ('create_date', '>=', fields.Datetime.now() - timedelta(hours=6))], limit=100)
        recs._try_send()
        old = self.sudo().search([('state', '=', 'pending'),
                                  ('create_date', '<', fields.Datetime.now() - timedelta(hours=6))])
        old.write({'state': 'skipped', 'note': _('Too old to send')})


class LeadCallLogMissedWa(models.Model):
    _inherit = 'lead.call.log'

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if not self.env.context.get('otm_odoo17_import'):
            for rec in recs:
                self.env['lead.missed.call.wa'].handle_missed_call(rec)
        return recs

    def write(self, vals):
        res = super().write(vals)
        if 'call_status' in vals or 'duration' in vals:
            for rec in self:
                self.env['lead.missed.call.wa'].handle_missed_call(rec)
        return res
