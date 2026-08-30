# -*- coding: utf-8 -*-
"""Meta (Facebook/Instagram) Lead Ads webhook.

Configure in the Meta App Dashboard > Webhooks > Page, subscribed to the
'leadgen' field:
    Callback URL : https://<your-odoo-domain>/api/meta/webhook
    Verify Token : Settings > Leads > Meta WhatsApp > Meta Verify Token

Requires Settings > Leads > Meta WhatsApp > Meta Page Access Token to be
set (a Page access token with the leads_retrieval permission) so the
webhook can call back to the Graph API for the actual lead field data —
Meta's webhook ping only contains the leadgen_id, not the answers.
"""
import json
import logging

import requests

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

GRAPH_API_VERSION = 'v19.0'


class MetaLeadWebhookController(http.Controller):

    @http.route('/api/meta/webhook', type='http', auth='public', csrf=False,
                methods=['GET', 'POST'])
    def meta_webhook(self, **kw):
        company = request.env.company.sudo()

        # ── GET: subscription verification handshake ───────────────────
        if request.httprequest.method == 'GET':
            mode = kw.get('hub.mode')
            token = kw.get('hub.verify_token')
            challenge = kw.get('hub.challenge')

            if mode == 'subscribe' and token and company.meta_verify_token and \
                    token == company.meta_verify_token:
                _logger.info("Meta webhook verified successfully.")
                return request.make_response(challenge or '', status=200)
            _logger.warning("Meta webhook verification failed (mode=%s).", mode)
            return request.make_response('Forbidden', status=403)

        # ── POST: leadgen notification ──────────────────────────────────
        try:
            data = json.loads(request.httprequest.data.decode())
        except Exception:
            data = {}

        try:
            if data.get('object') == 'page':
                for entry in data.get('entry', []):
                    for change in entry.get('changes', []):
                        value = change.get('value') or {}
                        if change.get('field') == 'leadgen' and value.get('leadgen_id'):
                            self._process_meta_lead(
                                company, value.get('leadgen_id'), value.get('ad_id'))
            return request.make_response('Success', status=200)
        except Exception:
            _logger.exception("Meta webhook processing failed")
            # Meta retries on non-2xx, which would just replay the same
            # bad payload — answer 200 and rely on the logged traceback.
            return request.make_response('Error', status=200)

    def _process_meta_lead(self, company, leadgen_id, ad_id):
        env = request.env
        access_token = company.meta_page_access_token
        if not access_token:
            _logger.error("Meta webhook: leadgen_id %s received but no Meta Page "
                          "Access Token is configured in Settings > Leads.", leadgen_id)
            return

        lead_resp = requests.get(
            f'https://graph.facebook.com/{GRAPH_API_VERSION}/{leadgen_id}',
            params={'access_token': access_token}, timeout=15)
        if lead_resp.status_code != 200:
            _logger.error("Meta webhook: failed to fetch lead %s from Graph API: %s",
                          leadgen_id, lead_resp.text)
            return
        lead_data = lead_resp.json()

        name = ''
        email = False
        phone = False
        for field in lead_data.get('field_data', []):
            field_name = (field.get('name') or '').lower()
            values = field.get('values') or []
            val = values[0] if values else ''
            if field_name in ('full_name', 'name'):
                name = val
            elif field_name == 'first_name':
                name = f"{val} {name}".strip() if name else val
            elif field_name == 'last_name':
                name = f"{name} {val}".strip() if name else val
            elif field_name in ('email', 'email_address'):
                email = val
            elif field_name in ('phone_number', 'phone'):
                phone = val
        name = name or 'Unknown Meta Lead'

        if not phone:
            # phone_number is a required field on leads.logic — a Meta
            # lead form that doesn't collect a phone number can't be
            # turned into a lead. Log it clearly rather than either
            # crashing or inventing a placeholder number.
            _logger.error(
                "Meta webhook: leadgen_id %s has no phone number in its field data "
                "(form may not collect one) — skipping lead creation. name=%r email=%r",
                leadgen_id, name, email)
            return

        # Dynamic Lead Source = the ad's campaign name (falls back to ad
        # name, then a flat default) so Meta leads land pre-segmented by
        # campaign instead of one big undifferentiated bucket.
        source_name = 'Meta Ad Lead'
        if ad_id:
            ad_resp = requests.get(
                f'https://graph.facebook.com/{GRAPH_API_VERSION}/{ad_id}',
                params={'fields': 'campaign{name},name', 'access_token': access_token},
                timeout=15)
            if ad_resp.status_code == 200:
                ad_data = ad_resp.json()
                source_name = (ad_data.get('campaign') or {}).get('name') \
                    or ad_data.get('name') or source_name
            else:
                _logger.warning("Meta webhook: failed to fetch ad %s name: %s",
                               ad_id, ad_resp.text)

        Source = env['leads.sources'].sudo()
        source = Source.search([('name', '=', source_name)], limit=1)
        if not source:
            source = Source.create({'name': source_name})

        env['leads.logic'].sudo().create({
            'name': name,
            'email_address': email,
            'phone_number': phone,
            'leads_source': source.id,
        })
        _logger.info("Meta webhook: created lead from leadgen_id %s, source '%s'.",
                    leadgen_id, source_name)
