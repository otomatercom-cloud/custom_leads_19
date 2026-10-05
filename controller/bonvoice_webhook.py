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

Bonvoice's payload field names are not documented publicly, so every lookup
is case-insensitive over several likely spellings, form or JSON bodies are
accepted, and the RAW payload is always written to the Odoo log
("Bonvoice webhook payload: ...") so field names can be tuned after the
first real call.  Answers are always HTTP 200 'success' so Bonvoice never
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
        ok = request.make_response('success', headers=[('Content-Type', 'text/plain')])
        expected = env['ir.config_parameter'].sudo().get_param(PARAM_TOKEN)
        given = request.params.get('token', '')
        if not expected or not hmac.compare_digest(str(given), str(expected)):
            _logger.warning('Bonvoice webhook: bad or missing token from %s', request.httprequest.remote_addr)
            return request.make_response('forbidden', status=403)

        data = self._payload()
        _logger.info('Bonvoice webhook payload: %s', data)
        if not data:
            return ok
        try:
            self._process(env, data)
        except Exception:
            _logger.exception('Bonvoice webhook processing failed')
        return ok

    def _process(self, env, data):
        g = self._g
        CallLog = env['lead.call.log'].sudo()
        Users = env['res.users'].sudo()

        call_id = g(data, 'call_uuid', 'calluuid', 'callid', 'call_id', 'uniqueid', 'unique_id',
                    'uuid', 'cdr_id', 'eventid', 'event_id')
        lead_param = g(data, 'lead_id')
        agent_param = g(data, 'agent_id')
        agent_no = g(data, 'agent_number', 'agentnumber', 'agent', 'agent_extension', 'extension',
                     'answered_by', 'destination')
        customer = g(data, 'legbdestination', 'customer_number', 'customernumber', 'callee',
                     'called_number', 'callednumber', 'dialed_number', 'to', 'caller_number',
                     'callernumber', 'caller', 'from', 'source')
        status = g(data, 'call_status', 'callstatus', 'status', 'disposition', 'dialstatus').upper()
        duration = g(data, 'conversation_duration', 'conversationduration', 'talk_time', 'talktime',
                     'billsec', 'duration', 'call_duration', 'callduration', 'total_duration')
        rec = g(data, 'recording_url', 'recordingurl', 'recording', 'record_url', 'recordingfile',
                'recording_file', 'recordurl', 'call_recording')
        direction = g(data, 'call_type', 'calltype', 'direction', 'calldirection', 'type').lower()

        lead = env['leads.logic'].sudo().browse()
        if lead_param.isdigit():
            lead = lead.browse(int(lead_param)).exists()
        user = Users.browse()
        if agent_param.isdigit():
            user = Users.browse(int(agent_param)).exists()
        if not user and agent_no:
            user = Users.search([('bonvoice_agent_number', '=', agent_no.replace('+', ''))], limit=1)
        incoming = 'in' in direction and 'out' not in direction
        if not lead and customer:
            lead = _V._find_or_create_lead(env, customer, 'incoming' if incoming else 'outgoing')

        log = CallLog.browse()
        if call_id:
            log = CallLog.search([('call_uuid', '=', call_id)], limit=1)
        if not log and lead and user:
            log = CallLog.search([
                ('lead_id', '=', lead.id), ('user_id', '=', user.id), ('call_uuid', '=', False),
                ('call_time', '>=', fields.Datetime.subtract(fields.Datetime.now(), hours=2)),
                ('remarks', 'like', 'Bourn Voice')], order='call_time desc', limit=1)

        vals = {'call_type': 'incoming' if incoming else 'outgoing'}
        if call_id:
            vals['call_uuid'] = call_id
        if lead:
            vals['lead_id'] = lead.id
        if user:
            vals['user_id'] = user.id
        if customer:
            vals['caller_number'] = customer
        if status:
            vals['call_status'] = 'NO ANSWER' if status in _FAILED else status
        if duration:
            vals['duration'] = duration
        if rec:
            vals['recording_url'] = rec
        if log:
            log.write(vals)
        elif lead or customer:
            vals.setdefault('call_time', fields.Datetime.now())
            vals.setdefault('remarks', 'Bourn Voice call (webhook)')
            CallLog.create(vals)
