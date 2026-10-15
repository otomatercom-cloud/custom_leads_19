# -*- coding: utf-8 -*-
"""Otomater Calls (Android app): company-phone calls and their recordings -> the lead's Call History.

The app signs in with the officer's own phone app key (Odoo: Leads Management > Phone App Key; an Odoo API key also works) sent as
    Authorization: Bearer <key>
Nothing is stored for numbers that are not a lead - those calls are ignored (personal calls stay private).

  POST /otm/mobile/ping        -> {ok, name}
  POST /otm/mobile/calls       JSON {"calls": [{"id","number","direction","time","duration"}]}
  POST /otm/mobile/recording   multipart: id=<call id>, file=<audio>
"""
import base64
import json
import logging
import mimetypes
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)
MAX_REC = 40 * 1024 * 1024


def _last10(v):
    return ''.join(c for c in str(v or '') if c.isdigit())[-10:]


def to_mp3(data):
    """Phone recorders save AMR / 3GP / M4A / WAV that browsers often cannot play. Make a small mono MP3.
    Returns bytes, None when ffmpeg is missing, False when the file is not readable audio (e.g. still being written)."""
    exe = shutil.which('ffmpeg')
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as d:
        src, dst = d + '/in.bin', d + '/out.mp3'
        with open(src, 'wb') as fh:
            fh.write(data)
        try:
            r = subprocess.run([exe, '-y', '-loglevel', 'error', '-i', src, '-vn', '-ac', '1', '-b:a', '64k', dst],
                               capture_output=True, timeout=180)
        except Exception:
            return False
        if r.returncode != 0:
            return False
        with open(dst, 'rb') as fh:
            out = fh.read()
    return out if len(out) > 1000 else False


class MobileCalls(http.Controller):

    # ── helpers ───────────────────────────────────────────────────────────────
    def _uid(self):
        auth = request.httprequest.headers.get('Authorization', '')
        key = auth[7:].strip() if auth.lower().startswith('bearer ') else ''
        if not key:
            return False
        uid = request.env['otm.mobile.key'].user_for_key(key)      # key made in Odoo: Leads > Phone App Key
        if uid:
            return uid
        try:
            uid = request.env['res.users.apikeys'].sudo()._check_credentials(scope='rpc', key=key)
        except Exception as e:  # wrong key / API changed
            _logger.info('mobile call app: key rejected (%s)', e)
            return False
        return uid or False

    def _json(self, data, status=200):
        return request.make_response(json.dumps(data), headers=[('Content-Type', 'application/json')], status=status)

    def _body(self):
        try:
            return json.loads(request.httprequest.get_data(as_text=True) or '{}')
        except ValueError:
            return {}

    def _find_lead(self, env, uid, number):
        n = _last10(number)
        if len(n) < 7:
            return env['leads.logic']
        Lead = env['leads.logic'].sudo().with_context(active_test=False)
        dom = [('phone_number', '=like', '%' + n)]
        mine = Lead.search(dom + [('lead_owner.user_id', '=', uid)], order='id desc', limit=1)
        return mine or Lead.search(dom, order='id desc', limit=1)

    # ── endpoints ─────────────────────────────────────────────────────────────
    @http.route('/otm/mobile/ping', type='http', auth='public', methods=['POST', 'GET'], csrf=False)
    def ping(self, **kw):
        uid = self._uid()
        if not uid:
            return self._json({'ok': False, 'error': 'Invalid API key'}, 401)
        user = request.env['res.users'].sudo().browse(uid)
        return self._json({'ok': True, 'name': user.name})

    @http.route('/otm/mobile/calls', type='http', auth='public', methods=['POST'], csrf=False)
    def calls(self, **kw):
        uid = self._uid()
        if not uid:
            return self._json({'ok': False, 'error': 'Invalid API key'}, 401)
        env = request.env
        Log = env['lead.call.log'].sudo()
        out = []
        for c in (self._body().get('calls') or [])[:200]:
            cid = str(c.get('id') or '')
            try:
                uuid = 'MOB-%s-%s' % (uid, cid)
                log = Log.search([('call_uuid', '=', uuid)], limit=1)
                if log:
                    out.append({'id': cid, 'matched': True, 'need_recording': not log.has_recording,
                                'lead_id': log.lead_id.id})
                    continue
                lead = self._find_lead(env, uid, c.get('number'))
                if not lead:
                    out.append({'id': cid, 'matched': False})
                    continue
                direction = str(c.get('direction') or 'out')
                secs = max(0, int(c.get('duration') or 0))
                when = datetime.utcfromtimestamp(int(c.get('time') or 0) / 1000.0)
                # the same call may already be in Bonvoice / Voxbay: never add a second copy
                near = Log.search_count([
                    ('lead_id', '=', lead.id), '|', ('call_uuid', '=', False), ('call_uuid', 'not like', 'MOB-%'),
                    ('call_time', '>=', when - timedelta(minutes=3)), ('call_time', '<=', when + timedelta(minutes=3))])
                if near:
                    out.append({'id': cid, 'matched': True, 'need_recording': False, 'lead_id': lead.id})
                    continue
                status = 'ANSWER' if secs > 0 else ('MISSED' if direction == 'missed' else 'NO ANSWER')
                with env.cr.savepoint():
                    log = Log.create({
                        'lead_id': lead.id, 'user_id': uid, 'call_time': when,
                        'call_uuid': uuid, 'caller_number': str(c.get('number') or ''),
                        'call_type': 'outgoing' if direction == 'out' else 'incoming',
                        'call_status': status, 'duration': '%02d:%02d:%02d' % (secs // 3600, secs % 3600 // 60, secs % 60),
                        'remarks': 'Company phone (mobile app)',
                    })
                out.append({'id': cid, 'matched': True, 'need_recording': secs > 5, 'lead_id': lead.id})
            except Exception as e:
                _logger.exception('mobile call %s failed', cid)
                out.append({'id': cid, 'matched': False, 'error': str(e)[:120]})
        return self._json({'ok': True, 'results': out})

    @http.route('/otm/mobile/recording', type='http', auth='public', methods=['POST'], csrf=False)
    def recording(self, **kw):
        uid = self._uid()
        if not uid:
            return self._json({'ok': False, 'error': 'Invalid API key'}, 401)
        cid = str(request.httprequest.form.get('id') or '')
        f = request.httprequest.files.get('file')
        log = request.env['lead.call.log'].sudo().search([('call_uuid', '=', 'MOB-%s-%s' % (uid, cid))], limit=1)
        if not log or not f:
            return self._json({'ok': False, 'error': 'Call not found'}, 404)
        data = f.read(MAX_REC + 1)
        if len(data) > MAX_REC:
            return self._json({'ok': False, 'error': 'File too large'}, 413)
        if len(data) < 2000:       # the phone's recorder is still writing the file: the app tries again later
            return self._json({'ok': False, 'error': 'Recording not ready'}, 422)
        name = f.filename or 'call.m4a'
        mp3 = to_mp3(data)
        if mp3 is False:
            return self._json({'ok': False, 'error': 'Recording not readable yet'}, 422)
        if mp3:
            log.write({'recording': base64.b64encode(mp3), 'recording_filename': 'call_%s.mp3' % cid,
                       'recording_mimetype': 'audio/mpeg'})
        else:                      # no ffmpeg on the server: keep the original file
            log.write({'recording': base64.b64encode(data), 'recording_filename': name,
                       'recording_mimetype': mimetypes.guess_type(name)[0] or 'audio/mp4'})
        return self._json({'ok': True})
