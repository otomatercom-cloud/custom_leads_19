# -*- coding: utf-8 -*-
"""Bonvoice (Bourn Voice) call-event / CDR webhook.

Configure in the Bonvoice panel (CDR / call-event / callback URL):
    https://<your-odoo-domain>/bonvoice/webhook?token=<secret>
The full URL (with the secret) is shown in Settings > Leads > Bonvoice.

How a call is matched
* Click-to-call sends  callBackParams {lead_id, agent_id}  and an eventID to
  Bonvoice; a callback echoing those params links straight to the lead/agent.
* Otherwise the call is matched by the Bonvoice call id, then by the customer
  number (lead phone) and the agent number (user.bonvoice_agent_number).

Field names are taken from the Odoo 17 production handler (known to work):
callID / call_id, SourceNumber, DestinationNumber, Direction ('Outbound' /
'Inbound'), CallDuration (seconds), Status, ResourceURL (recording link),
DataSource = 'Bonvoice'.  Lookups are case-insensitive, form or JSON bodies
are accepted, and the RAW payload is always written to the Odoo log
("Bonvoice webhook payload: ...").

The same handler also answers the legacy Odoo 17 paths
(/callcenterbridging and /api/voxbay/callcenterbridging) so a Bonvoice panel
already configured with those paths only needs its domain changed; Voxbay
events arriving on those paths are passed to the Voxbay handler.  Answers are always HTTP 200 'success' so Bonvoice never
retries in a loop.
"""
import hmac
import json
import logging

from odoo import fields, http
from odoo.http import request

from .voxbay_webhook import VoxbayWebhookController as _V

_logger = logging.getLogger(__name__)
PARAM_TOKEN = 'custom_leads_19.bonvoice_webhook_token'
_FAILED = {'BUSY', 'NOANSWER', 'NO ANSWER', 'NO_ANSWER', 'CONGESTION', 'CANCEL', 'CANCELLED',
           'FAILED', 'NOT ANSWERED', 'UNANSWERED', 'MISSED'}


def _flatten(obj, out):
    """Flatten nested dicts / JSON strings into one lowercase-keyed dict."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).strip().lower()
            if isinstance(v, str) and v.strip().startswith('{'):
                try:
                    v = json.loads(v)
                except ValueError:
                    pass
            if isinstance(v, (dict, list)):
                _flatten(v, out)
            else:
                out.setdefault(key, v)
    elif isinstance(obj, list):
        for item in obj:
            _flatten(item, out)


class BonvoiceWebhookController(http.Controller):

    @staticmethod
    def _payload():
        out = {}
        try:
            _flatten(dict(request.httprequest.values.items()), out)
        except Exception:
            pass
        try:
            raw = request.httprequest.get_data(as_text=True)
            if raw and raw.strip()[:1] in '{[':
                _flatten(json.loads(raw), out)
        except Exception:
            pass
        return out

    @staticmethod
    def _g(data, *names):
        for n in names:
            v = data.get(n.lower())
            if v not in (None, '', 'null', 'None'):
                return str(v).strip()
        return ''

    @http.route('/bonvoice/webhook', type='http', auth='public', methods=['POST', 'GET'], csrf=False)
    def bonvoice_webhook(self, **kwargs):
        env = request.env
        expected = env['ir.config_parameter'].sudo().get_param(PARAM_TOKEN)
        given = request.params.get('token', '')
        if not expected or not hmac.compare_digest(str(given), str(expected)):
            _logger.warning('Bonvoice webhook: bad or missing token from %s', request.httprequest.remote_addr)
            return request.make_response('forbidden', status=403)
        return self._handle(env)

    @http.route(['/callcenterbridging', '/api/voxbay/callcenterbridging'], type='http',
                auth='public', methods=['POST', 'GET'], csrf=False)
    def legacy_callcenterbridging(self, **kwargs):
        """Legacy Odoo 17 URL (no token, same as before)."""
        env = request.env
        data = self._payload()
        if self._is_bonvoice(data):
            return self._handle(env, data)
        from .voxbay_webhook import VoxbayWebhookController
        return VoxbayWebhookController().voxbay_webhook()

    @staticmethod
    def _is_bonvoice(data):
        return (str(data.get('datasource', '')).lower() == 'bonvoice' or 'resourceurl' in data
                or 'sourcenumber' in data or 'destinationnumber' in data)

    def _handle(self, env, data=None):
        ok = request.make_response('success', headers=[('Content-Type', 'text/plain')])
        data = data if data is not None else self._payload()
        _logger.info('Bonvoice webhook payload: %s', data)
        if not data:
            return ok
        try:
            self._process(env, data)
        except Exception:
            _logger.exception('Bonvoice webhook processing failed')
        return ok

    @staticmethod
    def _hms(raw):
        try:
            total = int(float(raw))
            h, rem = divmod(total, 3600)
            m, sec = divmod(rem, 60)
            return '{:02}:{:02}:{:02}'.format(h, m, sec)
        except (TypeError, ValueError):
            return str(raw or '00:00:00')

    def _process(self, env, data):
        g = self._g
        CallLog = env['lead.call.log'].sudo()
        Users = env['res.users'].sudo()

        call_id = g(data, 'callid', 'call_id', 'call_uuid', 'calluuid', 'uniqueid', 'uuid')
        src = g(data, 'sourcenumber', 'source_number', 'callernumber', 'caller')
        dst = g(data, 'destinationnumber', 'destination_number', 'destination', 'callee')
        direction = g(data, 'direction', 'calltype', 'call_type').lower()
        outgoing = direction.startswith('out') or (dst and not src)
        customer = dst if outgoing else src
        agent_ext = (src if outgoing else dst) or g(data, 'agentnumber', 'agent_number', 'extension')
        status = g(data, 'status', 'callstatus', 'call_status', 'disposition').upper() or 'ANSWERED'
        duration = self._hms(g(data, 'callduration', 'call_duration', 'duration', 'totalcallduration'))
        rec = g(data, 'resourceurl', 'recording_url', 'recordingurl', 'recording')
        lead_param = g(data, 'lead_id')
        agent_param = g(data, 'agent_id')

        if not customer and not lead_param:
            return
        lead = env['leads.logic'].sudo().browse()
        if lead_param.isdigit():
            lead = lead.browse(int(lead_param)).exists()
        if not lead and customer:
            lead = _V._find_or_create_lead(env, customer, 'outgoing' if outgoing else 'incoming')

        user = Users.browse()
        if agent_param.isdigit():
            user = Users.browse(int(agent_param)).exists()
        if not user and agent_ext:
            import re
            clean = re.sub(r'\D', '', agent_ext) or agent_ext.strip()
            cands = {c for c in (clean, clean.lstrip('0')) if c}
            user = Users.search([('bonvoice_agent_number', 'in', list(cands))], limit=1)

        log = CallLog.browse()
        if call_id:
            log = CallLog.search([('call_uuid', '=', call_id)], limit=1)
        if not log and lead:
            log = CallLog.search([
                ('lead_id', '=', lead.id), ('call_uuid', '=', False),
                ('call_time', '>=', fields.Datetime.subtract(fields.Datetime.now(), minutes=20))],
                order='call_time desc', limit=1)

        vals = {
            'call_type': 'outgoing' if outgoing else 'incoming',
            'caller_number': customer, 'call_status': 'NO ANSWER' if status in _FAILED else status,
            'duration': duration,
            'remarks': 'Bonvoice %s call. Status: %s. Duration: %s.' % (
                'outgoing' if outgoing else 'incoming', status, duration),
        }
        if lead:
            vals['lead_id'] = lead.id
        if call_id:
            vals['call_uuid'] = call_id
        if rec:
            vals['recording_url'] = rec
        # never blank out an already-known agent
        if user:
            vals['user_id'] = user.id
        if log:
            log.write(vals)
        else:
            vals.setdefault('call_time', fields.Datetime.now())
            CallLog.create(vals)
