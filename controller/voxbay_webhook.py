# -*- coding: utf-8 -*-
"""Voxbay call-event webhook.

One endpoint for every event Voxbay pushes (their panel sends all events to
a single URL): incoming landed / answered / disconnected / CDR, and
outgoing initiated / CDR. Event type is detected from which parameters are
present, exactly as the API document structures them.

Configure in the Voxbay panel:
    https://<your-odoo-domain>/voxbay/webhook

Notes on robustness:
* Voxbay's own doc mixes casings (CallUUID / CallUUlD / callUUlD), so all
  parameter lookups are case-insensitive.
* Voxbay may POST form-encoded or JSON — both are accepted.
* Response is the plain text "success" the doc expects (type='http', NOT
  Odoo's JSON-RPC wrapper).
"""
import json
import logging

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Voxbay statuses that mean the customer never talked to anyone
_FAILED_STATUSES = {'BUSY', 'NOANSWER', 'NO ANSWER', 'CONGESTION',
                    'CHANUNAVAIL', 'CANCEL', 'FAILED'}


class VoxbayWebhookController(http.Controller):

    # ── helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _params():
        """Merge form params and JSON body into one lowercase-keyed dict."""
        data = {}
        try:
            for k, v in request.httprequest.values.items():
                data[k.strip().lower()] = v
        except Exception:
            pass
        try:
            raw = request.httprequest.get_data(as_text=True)
            if raw and raw.strip().startswith('{'):
                for k, v in json.loads(raw).items():
                    data.setdefault(k.strip().lower(), v)
        except Exception:
            pass
        return data

    @staticmethod
    def _get(data, *names):
        """Fetch first present parameter among spelling variants."""
        for name in names:
            val = data.get(name.lower())
            if val not in (None, ''):
                return str(val).strip()
        return ''

    @staticmethod
    def _normalize_recording_url(url):
        """Voxbay's CDR may send just a filename (see their doc example
        '844200600-18042018-110738.wav'). Prefix the documented base URL
        so the link is playable from Odoo."""
        url = (url or '').strip()
        if url and not url.lower().startswith(('http://', 'https://')):
            url = 'https://x.voxbay.com:81/callcenter/' + url.lstrip('/')
        return url

    @staticmethod
    def _find_lead(env, number):
        number = (number or '').replace(' ', '').replace('+', '')
        if not number:
            return env['leads.logic'].sudo().browse()
        last10 = number[-10:] if len(number) >= 10 else number
        return env['leads.logic'].sudo().search(
            [('phone_number', 'like', '%' + last10)], limit=1)

    @staticmethod
    def _find_user_by_extension(env, agent):
        agent = (agent or '').strip()
        if not agent:
            return env['res.users'].sudo().browse()
        return env['res.users'].sudo().search(
            [('voxbay_user_no', '=', agent)], limit=1)

    @staticmethod
    def _log_by_uuid(env, call_uuid):
        if not call_uuid:
            return env['lead.call.log'].sudo().browse()
        return env['lead.call.log'].sudo().search(
            [('call_uuid', '=', call_uuid)], limit=1)

    # ── the endpoint ─────────────────────────────────────────────────
    @http.route(['/voxbay/webhook', '/voxbay/cdr'], type='http',
                auth='public', methods=['POST', 'GET'], csrf=False)
    def voxbay_webhook(self, **kwargs):
        env = request.env
        data = self._params()
        _logger.info("Voxbay webhook payload: %s", data)

        try:
            call_uuid = self._get(data, 'CallUUID', 'CallUUlD', 'callUUID',
                                  'callUUlD', 'call_uuid', 'calluuid')
            CallLog = env['lead.call.log'].sudo()

            # ---- OUTGOING (extension present) -----------------------
            extension = self._get(data, 'extension')
            if extension:
                destination = self._get(data, 'destination')
                duration = self._get(data, 'duration')
                status = self._get(data, 'status', 'callStatus').upper()
                user = self._find_user_by_extension(env, extension)
                # Voxbay extension may look like 'abc*017_452' — try the
                # tail after * / _ as well
                if not user:
                    for sep in ('*', '_'):
                        if sep in extension:
                            user = self._find_user_by_extension(
                                env, extension.rsplit(sep, 1)[-1])
                            if user:
                                break
                lead = self._find_lead(env, destination)

                log = self._log_by_uuid(env, call_uuid)
                if not log and user:
                    # Attach to the click-to-call stub made by
                    # action_voxbay_call (created without a UUID) — most
                    # recent uuid-less log for this agent in the last hour.
                    log = CallLog.search([
                        ('user_id', '=', user.id),
                        ('call_uuid', '=', False),
                        ('call_time', '>=', fields.Datetime.subtract(
                            fields.Datetime.now(), hours=1)),
                        ('remarks', 'like', 'Voxbay'),
                    ], order='call_time desc', limit=1)

                vals = {
                    'call_type': 'outgoing',
                    'caller_number': destination or (log.caller_number if log else ''),
                }
                if call_uuid:
                    vals['call_uuid'] = call_uuid
                if user:
                    vals['user_id'] = user.id
                if lead:
                    vals['lead_id'] = lead.id
                if status:
                    vals['call_status'] = status
                if duration:
                    vals['duration'] = duration
                rec_url = self._get(data, 'recording_URL', 'recording_url',
                                    'recordingURL')
                if rec_url:
                    vals['recording_url'] = self._normalize_recording_url(rec_url)

                if log:
                    log.write(vals)
                else:
                    vals.setdefault('call_time', fields.Datetime.now())
                    vals.setdefault('remarks', 'Voxbay outgoing call')
                    CallLog.create(vals)
                return request.make_response(
                    'success', headers=[('Content-Type', 'text/plain')])

            # ---- INCOMING -------------------------------------------
            caller = self._get(data, 'callerNumber', 'caller_number')
            called = self._get(data, 'calledNumber', 'called_number')
            agent = self._get(data, 'AgentNumber', 'agentNumber',
                              'agent_number')
            total_dur = self._get(data, 'totalCallDuration',
                                  'total_call_duration')
            conv_dur = self._get(data, 'conversationDuration',
                                 'conversation_duration')
            status = self._get(data, 'callStatus', 'call_status').upper()
            rec_url = self._get(data, 'recording_URL', 'recording_url',
                                'recordingURL')

            log = self._log_by_uuid(env, call_uuid)
            lead = self._find_lead(env, caller)
            user = self._find_user_by_extension(env, agent)

            is_cdr = bool(total_dur or conv_dur or status or rec_url)

            vals = {'call_type': 'incoming'}
            if call_uuid:
                vals['call_uuid'] = call_uuid
            if caller:
                vals['caller_number'] = caller
            if lead:
                vals['lead_id'] = lead.id
            if user:
                vals['user_id'] = user.id

            if is_cdr:
                # Event 4: final CDR — conversationDuration is real talk
                # time; totalCallDuration includes ring/IVR time.
                vals['duration'] = conv_dur or total_dur or ''
                vals['call_status'] = status or 'ANSWERED'
                if rec_url:
                    vals['recording_url'] = self._normalize_recording_url(rec_url)
                remark_bits = []
                dtmf = self._get(data, 'dtmf')
                if dtmf:
                    remark_bits.append('DTMF: %s' % dtmf)
                transferred = self._get(data, 'transferredNumber',
                                        'transferred_number')
                if transferred:
                    remark_bits.append('Transferred: %s' % transferred)
                if remark_bits:
                    vals['remarks'] = ' | '.join(remark_bits)
            elif agent and not called:
                # Event 2: answered by agent
                vals['call_status'] = 'ANSWERED'
            elif agent and not caller:
                # Event 3: disconnected (AgentNumber + UUID only)
                vals.pop('call_type', None)  # don't overwrite anything else
            # Event 1 (landed): calledNumber + callerNumber + UUID → just
            # the stub with caller/lead set above.

            if log:
                log.write(vals)
            else:
                vals.setdefault('call_time', fields.Datetime.now())
                vals.setdefault('remarks', 'Voxbay incoming call')
                CallLog.create(vals)

            return request.make_response(
                'success', headers=[('Content-Type', 'text/plain')])

        except Exception:
            _logger.exception("Voxbay webhook processing failed")
            # Still answer success so Voxbay doesn't retry-flood; payload
            # is in the log above for debugging.
            return request.make_response(
                'success', headers=[('Content-Type', 'text/plain')])
