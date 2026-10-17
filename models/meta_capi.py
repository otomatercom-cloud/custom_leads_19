# -*- coding: utf-8 -*-
"""Meta Conversions API for CRM ("Conversion Leads"): when a Meta lead's Lead Quality changes, the matching CRM event
(Lead / Qualified / Admission ...) is sent to the Meta dataset so Meta can find more people like the good leads.

Flow: lead quality changes  ->  a row is queued in otm.meta.capi.log  ->  cron sends it to
POST https://graph.facebook.com/<ver>/<dataset_id>/events  with  action_source=system_generated,
custom_data.event_source=crm, user_data.lead_id=<leadgen_id>.  Sending is done by cron, never inside the save,
so a Meta outage can not block an officer. Needs the Meta leadgen_id on the lead (field meta_leadgen_id)."""
import logging
import time

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
P = 'custom_leads_19.meta_capi_'
MAX_TRIES = 5


class OtmMetaCapiMap(models.Model):
    _name = 'otm.meta.capi.map'
    _description = 'Meta CRM Event Mapping'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    quality_id = fields.Many2one('lead.quality.config', string='Lead Quality', required=True, ondelete='cascade')
    event_name = fields.Char(string='Meta CRM event', required=True,
                             help='The event name Meta receives, e.g. Lead, Qualified, Admission. '
                                  'Use the same names you chose in Meta (CRM events of the ad set).')
    active = fields.Boolean(default=True)

    _quality_uniq = models.Constraint('unique(quality_id)', 'This lead quality already has an event.')


class OtmMetaCapiLog(models.Model):
    _name = 'otm.meta.capi.log'
    _description = 'Meta CRM Event Log'
    _order = 'id desc'

    lead_id = fields.Many2one('leads.logic', required=True, index=True, ondelete='cascade')
    leadgen_id = fields.Char(index=True)
    event_name = fields.Char(required=True)
    event_time = fields.Datetime(default=fields.Datetime.now)
    state = fields.Selection([('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')],
                             default='pending', index=True)
    tries = fields.Integer()
    response = fields.Text()

    _lead_event_uniq = models.Constraint('unique(lead_id, event_name)', 'Event already queued for this lead.')

    @api.model
    def _cfg(self, key, default=''):
        return self.env['ir.config_parameter'].sudo().get_param(P + key, default)

    @api.model
    def cron_send(self):
        if self._cfg('enabled') not in ('True', 'true', '1'):
            return
        dataset, token = self._cfg('dataset_id').strip(), self._cfg('token').strip()
        if not dataset or not token:
            return
        recs = self.sudo().search([('state', '=', 'pending'), ('tries', '<', MAX_TRIES)], order='id', limit=200)
        if recs:
            recs._send(dataset, token)

    def action_send_now(self):
        dataset, token = self._cfg('dataset_id').strip(), self._cfg('token').strip()
        if not dataset or not token:
            raise UserError(_('Set the Dataset ID and Access Token in Settings > Leads > Meta CRM events first.'))
        self.filtered(lambda r: r.state != 'sent')._send(dataset, token)

    def action_requeue(self):
        self.sudo().write({'state': 'pending', 'tries': 0})

    def _send(self, dataset, token):
        ver = self._cfg('version', 'v21.0') or 'v21.0'
        crm = self._cfg('crm_name', 'Odoo') or 'Odoo'
        url = 'https://graph.facebook.com/%s/%s/events' % (ver, dataset)
        for rec in self.sudo():
            lid = (rec.leadgen_id or '').strip()
            if not lid:
                rec.write({'state': 'failed', 'response': 'No Meta leadgen_id on the lead'})
                continue
            # Meta wants UTC epoch seconds; Odoo datetimes are naive UTC
            ts = int((fields.Datetime.to_datetime(rec.event_time) - fields.Datetime.to_datetime('1970-01-01 00:00:00')).total_seconds()) \
                if rec.event_time else int(time.time())
            payload = {'data': [{
                'event_name': rec.event_name,
                'event_time': ts,
                'action_source': 'system_generated',
                'user_data': {'lead_id': int(lid) if lid.isdigit() else lid},
                'custom_data': {'event_source': 'crm', 'lead_event_source': crm},
            }]}
            try:
                r = requests.post(url, params={'access_token': token}, json=payload, timeout=20)
                ok = r.status_code == 200 and not (r.json() or {}).get('error')
                rec.write({'tries': rec.tries + 1, 'state': 'sent' if ok else 'pending',
                           'response': (r.text or '')[:2000]})
                if not ok:
                    _logger.warning('Meta CAPI %s for lead %s failed: %s', rec.event_name, rec.lead_id.id, r.text[:300])
            except Exception as e:  # noqa: BLE001
                rec.write({'tries': rec.tries + 1, 'response': str(e)[:500]})
            if rec.state == 'pending' and rec.tries >= MAX_TRIES:
                rec.state = 'failed'


class LeadsLogicMetaCapi(models.Model):
    _inherit = 'leads.logic'

    meta_leadgen_id = fields.Char(string='Meta Lead ID', index=True, copy=False,
                                  help='The leadgen_id Meta gave this lead. Needed to report the lead quality '
                                       'back to Meta (Settings > Leads > Meta CRM events).')

    def _meta_capi_queue(self):
        """Queue the CRM event that matches each lead's current quality (once per lead and event)."""
        if self.env['otm.meta.capi.log']._cfg('enabled') not in ('True', 'true', '1'):
            return
        Map, Log = self.env['otm.meta.capi.map'].sudo(), self.env['otm.meta.capi.log'].sudo()
        events = {m.quality_id.code: m.event_name for m in Map.search([])}
        for lead in self.sudo().filtered('meta_leadgen_id'):
            ev = events.get(lead.lead_quality)
            if ev and not Log.search_count([('lead_id', '=', lead.id), ('event_name', '=', ev)]):
                Log.create({'lead_id': lead.id, 'leadgen_id': lead.meta_leadgen_id, 'event_name': ev})

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        try:
            recs.filtered('meta_leadgen_id')._meta_capi_queue()
        except Exception as e:  # noqa: BLE001  never block lead creation
            _logger.warning('Meta CAPI queue failed on create: %s', e)
        return recs

    def write(self, vals):
        res = super().write(vals)
        if 'lead_quality' in vals or vals.get('meta_leadgen_id'):
            try:
                self._meta_capi_queue()
            except Exception as e:  # noqa: BLE001
                _logger.warning('Meta CAPI queue failed on write: %s', e)
        return res


class ResConfigSettingsMetaCapi(models.TransientModel):
    _inherit = 'res.config.settings'

    meta_capi_enabled = fields.Boolean(string='Send lead quality to Meta', config_parameter=P + 'enabled')
    meta_capi_dataset_id = fields.Char(string='Dataset ID', config_parameter=P + 'dataset_id',
                                       help='Events Manager > Data sources > your dataset (Pixel) > ID.')
    meta_capi_token = fields.Char(string='Conversions API access token', config_parameter=P + 'token',
                                  help='Events Manager > dataset > Settings > Conversions API > Generate access token.')
    meta_capi_crm_name = fields.Char(string='CRM name', config_parameter=P + 'crm_name', default='Odoo',
                                     help='Shown in Meta as the source of the events.')
    meta_capi_version = fields.Char(string='Graph API version', config_parameter=P + 'version', default='v21.0')
