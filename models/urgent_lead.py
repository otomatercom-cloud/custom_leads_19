# -*- coding: utf-8 -*-
"""Urgent new-lead popup.

When a lead with quality **New** is given to an admission officer (created with an owner,
assigned by the round-robin / pool, or reassigned), the officer's browser shows an
"URGENT - call now" card with the lead details - on any screen, also during a call.
The card keeps coming back (every few minutes) until the lead's quality changes from New.
"""
import logging
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)
PARAM_URGENT = 'custom_leads_19.urgent_lead_popup'
UNWORKED = (False, 'new', 'first_attempt')
PARAM_URGENT_AGE = 'custom_leads_19.urgent_age_days'      # lead must have arrived within this many days before today (0 = today only)
PARAM_RNR_HOUR = 'custom_leads_19.urgent_rnr_hour'       # after this hour (IST) officers get the "RNR call needed" popup, 0 = off
PARAM_URGENT_SRC = 'custom_leads_19.urgent_source_ids'   # comma separated lead source ids, empty = all
BUS_OPEN = 'urgent_lead'
BUS_CLOSE = 'urgent_lead_close'
MAX_AGE_HOURS = 24


class LeadUrgentAlert(models.Model):
    _name = 'lead.urgent.alert'
    _description = 'Urgent New Lead Alert'
    _order = 'id desc'

    lead_id = fields.Many2one('leads.logic', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    state = fields.Selection([('pending', 'Pending'), ('closed', 'Closed')], default='pending', index=True)
    kind = fields.Selection([('new', 'New lead'), ('rnr', 'RNR call needed')], default='new', required=True, index=True)
    snooze_until = fields.Datetime()
    closed_date = fields.Datetime()
    close_reason = fields.Char()

    # ------------------------------------------------------------------ helpers
    @api.model
    def _enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(PARAM_URGENT) != '0'

    @api.model
    def _source_ids(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_URGENT_SRC) or ''
        return [int(x) for x in raw.split(',') if x.strip().isdigit()]

    @api.model
    def _today_start(self):
        """Start of today (Asia/Kolkata) as naive UTC."""
        tz = pytz.timezone('Asia/Kolkata')
        local = datetime.now(pytz.utc).astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def _age_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_URGENT_AGE)
        try:
            return max(0, int(raw)) if raw not in (None, False, '') else 1
        except ValueError:
            return 1

    @api.model
    def _source_ok(self, lead):
        """True when the popup applies to this lead: right source (empty = all) and it arrived yesterday or today."""
        ids = self._source_ids()
        if ids and lead.leads_source.id not in ids:
            return False
        limit = self._today_start() - timedelta(days=self._age_days())
        return not lead.create_date or lead.create_date >= limit

    @api.model
    def _called_since(self, lead, uid, since):
        return bool(self.env['lead.call.log'].sudo().search_count([
            ('lead_id', '=', lead.id), ('user_id', '=', uid), ('call_type', '!=', 'incoming'),
            ('call_time', '>=', since)]))

    @api.model
    def cron_rnr_alerts(self):
        """After noon: a lead still New/First Attempt that was called but never answered, and was not
        called again since noon, gets an 'RNR call needed' popup for its officer."""
        if not self._enabled():
            return
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_RNR_HOUR)
        hour = int(raw) if (raw or '').strip().isdigit() else 12
        if not hour:
            return
        today = self._today_start()
        noon = today + timedelta(hours=hour)
        if fields.Datetime.now() < noon:
            return
        from .call_report import _parse_duration_seconds
        Lead = self.env['leads.logic'].sudo()
        leads = Lead.search([
            ('lead_owner', '!=', False), ('state', '!=', 'lost'),
            ('lead_quality', 'in', list(UNWORKED)),
            ('create_date', '>=', today - timedelta(days=self._age_days())),
        ], limit=500)
        for lead in leads:
            user = lead.lead_owner.user_id
            if not user or not user.active or not self._source_ok(lead):
                continue
            calls = lead.call_log_ids.filtered(lambda c: c.call_type != 'incoming')
            if not calls or any(_parse_duration_seconds(c.duration) > 0 for c in lead.call_log_ids):
                continue
            if any(c.user_id == user and c.call_time and c.call_time >= noon for c in calls):
                continue
            if self.sudo().search_count([('lead_id', '=', lead.id), ('user_id', '=', user.id),
                                         ('kind', '=', 'rnr'), ('create_date', '>=', today)]):
                continue
            alert = self.sudo().create({'lead_id': lead.id, 'user_id': user.id, 'kind': 'rnr'})
            try:
                alert._notify()
            except Exception:  # noqa: BLE001
                _logger.exception('RNR popup: bus notification failed')

    def _payload(self):
        self.ensure_one()
        lead = self.lead_id.sudo()
        campaign = lead.source_campaign_id.name if 'source_campaign_id' in lead._fields and lead.source_campaign_id else ''
        calls = lead.call_log_ids.filtered(lambda c: c.call_type != 'incoming')
        return {
            'id': self.id,
            'kind': self.kind or 'new',
            'calls': len(calls),
            'lead_id': lead.id,
            'name': lead.name or '',
            'phone': lead.phone_number or '',
            'email': lead.email_address or '',
            'source': lead.leads_source.name or '',
            'campaign': campaign,
            'course': lead.course_interested or '',
            'place': lead.place or '',
            'remarks': lead.remarks or '',
            'received': fields.Datetime.to_string(self.create_date) if self.create_date else '',
        }

    def _notify(self):
        for alert in self:
            self.env['bus.bus']._sendone(alert.user_id.partner_id, BUS_OPEN, alert._payload())

    def _close(self, reason):
        alerts = self.filtered(lambda a: a.state == 'pending')
        for alert in alerts:
            self.env['bus.bus']._sendone(alert.user_id.partner_id, BUS_CLOSE,
                                         {'id': alert.id, 'lead_id': alert.lead_id.id})
        alerts.write({'state': 'closed', 'closed_date': fields.Datetime.now(), 'close_reason': reason})

    # ------------------------------------------------------------------ RPC used by the popup
    @api.model
    def get_my_pending(self):
        """Alerts for the current user that should be on screen now. Also closes stale ones."""
        if not self._enabled():
            return []
        me, now = self.env.uid, fields.Datetime.now()
        alerts = self.sudo().search([('user_id', '=', me), ('state', '=', 'pending')])
        out = []
        for a in alerts:
            lead = a.lead_id
            ok_quality = (lead.lead_quality in UNWORKED) if a.kind == 'rnr' else (lead.lead_quality == 'new')
            if (not ok_quality or lead.lead_owner.user_id.id != me or not self._source_ok(lead)
                    or a.create_date < self._today_start()):   # the popup is for leads assigned today only
                a._close('no longer needed')
                continue
            if self._called_since(lead, me, a.create_date):    # the officer has already called -> hide
                a._close('called')
                continue
            if a.snooze_until and a.snooze_until > now:
                continue
            out.append(a._payload())
        return out

    def action_snooze(self, minutes=5):
        for a in self.sudo().filtered(lambda r: r.user_id.id == self.env.uid):
            a.snooze_until = fields.Datetime.now() + timedelta(minutes=minutes)
        return True

    def action_call(self):
        """Start the call exactly like the Call button on the lead, then remind again in 15 min if still New."""
        self.ensure_one()
        alert = self.sudo()
        if alert.user_id.id != self.env.uid:
            return False
        alert.snooze_until = fields.Datetime.now() + timedelta(minutes=15)
        lead = self.env['leads.logic'].browse(alert.lead_id.id)
        company = self.env.company
        provider = lead._call_provider_for_user()
        if provider == 'bonvoice':
            act = lead.action_bonvoice_call()
        elif provider == 'voxbay':
            act = lead.action_voxbay_call()
        else:                                   # softphone / phone app
            act = lead.action_kanban_start_call()
        return self._web_action(act)

    @api.model
    def _web_action(self, act):
        """Actions returned through a plain RPC call (not a button) need `views`, or the web client
        fails with "Cannot read properties of undefined (reading 'map')"."""
        if isinstance(act, dict) and act.get('type') == 'ir.actions.act_window' and not act.get('views'):
            modes = (act.get('view_mode') or 'form').split(',')
            act = dict(act, views=[(act.get('view_id') and act['view_id'][0] or False, m.strip()) for m in modes])
        return act


class LeadsLogicUrgent(models.Model):
    _inherit = 'leads.logic'

    def _urgent_skip(self):
        ctx = self.env.context
        return (ctx.get('otm_odoo17_import') or ctx.get('install_mode') or ctx.get('urgent_lead_skip')
                or not self.env['lead.urgent.alert']._enabled())

    def _urgent_raise(self):
        if self._urgent_skip():
            return
        Alert = self.env['lead.urgent.alert'].sudo()
        for lead in self.sudo():
            user = lead.lead_owner.user_id
            if (lead.lead_quality != 'new' or not user or not user.active or not Alert._source_ok(lead)
                    or user.id == self.env.uid):        # an officer creating a lead for themselves needs no alert
                continue
            alert = Alert.search([('lead_id', '=', lead.id), ('user_id', '=', user.id), ('state', '=', 'pending'), ('kind', '=', 'new')], limit=1)
            if alert:
                alert.snooze_until = False
            else:
                alert = Alert.create({'lead_id': lead.id, 'user_id': user.id})
            try:
                alert._notify()
            except Exception:  # bus problems must never block saving a lead
                _logger.exception('Urgent lead popup: bus notification failed')

    def _urgent_close(self, reason='quality changed', users=None, kinds=None):
        domain = [('lead_id', 'in', self.ids), ('state', '=', 'pending')]
        if kinds:
            domain.append(('kind', 'in', kinds))
        if users:
            domain.append(('user_id', 'in', users.ids))
        self.env['lead.urgent.alert'].sudo().search(domain)._close(reason)

    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        leads._urgent_raise()
        return leads

    def write(self, vals):
        old_owner = {l.id: l.lead_owner.user_id for l in self} if 'lead_owner' in vals else {}
        res = super().write(vals)
        if 'lead_quality' in vals:
            for lead in self:
                if lead.lead_quality != 'new':
                    lead._urgent_close(kinds=['new'])
                if lead.lead_quality not in UNWORKED:
                    lead._urgent_close()
        if old_owner:
            changed = self.filtered(lambda l: l.lead_owner.user_id != old_owner.get(l.id))
            for lead in changed:
                if old_owner.get(lead.id):
                    lead._urgent_close('reassigned', users=old_owner[lead.id])
            changed._urgent_raise()
        return res


class LeadCallLogUrgent(models.Model):
    _inherit = 'lead.call.log'

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if not self.env.context.get('otm_odoo17_import'):
            try:
                for rec in recs:
                    if rec.lead_id and rec.user_id and rec.call_type != 'incoming':
                        rec.lead_id._urgent_close('called', users=rec.user_id)
            except Exception:  # noqa: BLE001 - never block call logging
                _logger.exception('Urgent popup close after call failed')
        return recs
