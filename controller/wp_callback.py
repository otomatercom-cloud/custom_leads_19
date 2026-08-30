# -*- coding: utf-8 -*-
"""WordPress contact/enquiry form → lead bridge.

Point your WordPress form plugin's webhook/POST-to-URL at:
    https://<your-odoo-domain>/api/wp/callback

Expected JSON body: {"name": "...", "phone": "...", "email": "...",
"course": "..."}. Falls back to leads.sources 'Digital Leads' when no
explicit source is given (matches how the Voxbay/Meta bridges name
their fallback sources).
"""
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

_CORS_HEADERS = [
    ('Access-Control-Allow-Origin', '*'),
    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
    ('Access-Control-Allow-Headers', 'Content-Type'),
]


class WordpressCallbackController(http.Controller):

    @http.route('/api/wp/callback', type='http', auth='public', csrf=False,
                methods=['POST', 'OPTIONS'])
    def wp_callback(self, **kw):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=_CORS_HEADERS, status=200)

        try:
            data = json.loads(request.httprequest.data.decode())
        except Exception:
            _logger.warning("WP callback: could not parse JSON body.")
            return self._json_response({'status': 'error', 'message': 'Invalid JSON body'})

        name = (data.get('name') or '').strip()
        phone = (data.get('phone') or data.get('phone_number') or '').strip()
        email = (data.get('email') or data.get('email_address') or '').strip()
        course = (data.get('course') or data.get('preferred_course') or '').strip()
        source_name = (data.get('source') or 'Digital Leads').strip() or 'Digital Leads'

        if not name or not phone:
            # name and phone_number are both required on leads.logic —
            # fail fast with a clear message instead of an opaque 500
            # from the ORM's own required-field ValidationError.
            _logger.warning("WP callback: missing name or phone in payload: %s", data)
            return self._json_response({
                'status': 'error',
                'message': 'Both "name" and "phone" are required.',
            })

        try:
            Source = request.env['leads.sources'].sudo()
            source = Source.search([('name', '=', source_name)], limit=1)
            if not source:
                source = Source.create({'name': source_name})

            lead = request.env['leads.logic'].sudo().create({
                'name': name,
                'phone_number': phone,
                'email_address': email or False,
                'preferred_course': course or False,
                'leads_source': source.id,
            })
            _logger.info("WP callback: created lead %s (id=%s) from source '%s'.",
                        name, lead.id, source_name)
            return self._json_response({'status': 'success', 'lead_id': lead.id})

        except Exception as e:
            _logger.exception("WP callback: failed to create lead.")
            return self._json_response({'status': 'error', 'message': str(e)})

    @staticmethod
    def _json_response(payload):
        headers = [('Content-Type', 'application/json')] + _CORS_HEADERS
        return request.make_response(json.dumps(payload), headers=headers)
