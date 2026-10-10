# -*- coding: utf-8 -*-
"""Urgent new-lead popup.

When a lead with quality **New** is given to an admission officer (created with an owner,
assigned by the round-robin / pool, or reassigned), the officer's browser shows an
"URGENT - call now" card with the lead details - on any screen, also during a call.
The card keeps coming back (every few minutes) until the lead's quality changes from New.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)
PARAM_URGENT = 'custom_leads_19.urgent_lead_popup'
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
    snooze_until = fields.Datetime()
    closed_date = fields.Datetime()
    close_reason = fields.Char()

    # ------------------------------------------------------------------ helpers
    @api.model
    def _enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(PARAM_URGENT) != '0'

    def _payload(self):
        self.ensure_one()
        lead = self.lead_id.sudo()
        campaign = lead.source_campaign_id.name if 'source_campaign_id' in lead._fields and lead.source_campaign_id else ''
        return {
            'id': self.id,
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
            if (lead.lead_quality != 'new' or lead.lead_owner.user_id.id != me
                    or a.create_date < now - timedelta(hours=MAX_AGE_HOURS)):
                a._close('no longer needed')
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
        if company.bonvoice_username and self.env.user.bonvoice_agent_number:
            return lead.action_bonvoice_call()
        return lead.action_kanban_start_call()


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
            if (lead.lead_quality != 'new' or not user or not user.active
                    or user.id == self.env.uid):        # an officer creating a lead for themselves needs no alert
                continue
            alert = Alert.search([('lead_id', '=', lead.id), ('user_id', '=', user.id), ('state', '=', 'pending')], limit=1)
            if alert:
                alert.snooze_until = False
            else:
                alert = Alert.create({'lead_id': lead.id, 'user_id': user.id})
            try:
                alert._notify()
            except Exception:  # bus problems must never block saving a lead
                _logger.exception('Urgent lead popup: bus notification failed')

    def _urgent_close(self, reason='quality changed', users=None):
        domain = [('lead_id', 'in', self.ids), ('state', '=', 'pending')]
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
            self.filtered(lambda l: l.lead_quality != 'new')._urgent_close()
        if old_owner:
            changed = self.filtered(lambda l: l.lead_owner.user_id != old_owner.get(l.id))
            for lead in changed:
                if old_owner.get(lead.id):
                    lead._urgent_close('reassigned', users=old_owner[lead.id])
            changed._urgent_raise()
        return res
