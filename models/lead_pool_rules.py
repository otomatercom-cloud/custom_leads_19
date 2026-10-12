# -*- coding: utf-8 -*-
"""Pool round-robin extras (configured on the active Pool rule):
 1. 'Ringing Not Responding' only after N calls.
 2. A New lead whose quality is changed by its officer moves to the next officer.
 3. A lead not called enough on the day it was assigned moves to another officer next day."""
from datetime import timedelta
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

UNWORKED = (False, 'new', 'first_attempt')


class LeadsLogicPoolRules(models.Model):
    _inherit = 'leads.logic'

    auto_reassign_count = fields.Integer(string='Auto Reassignments', default=0, copy=False, readonly=True)
    is_abroad = fields.Boolean(
        string='Abroad Lead', index=True, copy=False, tracking=True,
        help='Tick for a lead living abroad (they usually answer on WhatsApp, not the phone). The lead moves to '
             'the Abroad menu and is left out of the automatic rules: no automatic Ringing Not Responding '
             'after N calls, no automatic reassignment, no RNR popup.')

    def action_mark_abroad(self):
        self.write({'is_abroad': True})
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Abroad'), 'message': _('%s lead(s) moved to the Abroad menu.') % len(self),
                           'type': 'success'}}

    def action_unmark_abroad(self):
        self.write({'is_abroad': False})
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Abroad'), 'message': _('%s lead(s) moved back to Leads.') % len(self),
                           'type': 'success'}}

    def _pool_rule(self):
        rules = self.env['lead.assignment.rule'].sudo().search([('active', '=', True)], order='sequence, id')
        lead = self[:1]
        rule = next((r for r in rules
                     if r.assignment_type != 'attendance_pool' or not lead or r._pool_accepts(lead)), False)
        return rule if rule and rule.assignment_type == 'attendance_pool' else False

    def write(self, vals):
        reassign = self.env['leads.logic']
        rule = False
        if 'lead_quality' in vals and not self.env.context.get('skip_pool_rules') and not self.env.su:
            rule = self._pool_rule()
            new_q = vals.get('lead_quality')
            # one setting for everyone: Settings > Leads > Lead rules
            need = self.env['otm.lead.rule.params'].param('custom_leads_19.rnr_min_calls')
            if need and new_q == 'not_responding':
                for rec in self:
                    if rec.lead_quality != 'not_responding' and rec.call_count < need and not rec.is_abroad:
                        raise UserError(_(
                            "'Ringing Not Responding' needs at least %(need)s calls and this lead has "
                            "only %(have)s. Call the lead again first.") % {'need': need, 'have': rec.call_count})
        if rule:
            new_q = vals.get('lead_quality')
            mode = rule.pool_reassign_on_quality
            if mode in ('no_call', 'always') and new_q and new_q != 'new':
                for rec in self:
                    if (not rec.is_abroad and rec.lead_quality in (False, 'new') and rec.lead_owner
                            and rec.sudo().lead_owner.user_id.id == self.env.uid
                            and (mode == 'always' or not rec.call_count)):
                        reassign |= rec
        res = super().write(vals)
        for rec in reassign:
            rule._pool_reassign_lead(
                rec, _("quality changed to %s on a new lead") % (
                    dict(rec._fields['lead_quality'].selection).get(rec.lead_quality, rec.lead_quality)))
        return res


class LeadAssignmentRulePoolRules(models.Model):
    _inherit = 'lead.assignment.rule'

    def _pool_reassign_lead(self, lead, reason):
        """Move `lead` to another eligible officer. Returns True when it moved."""
        self.ensure_one()
        lead = lead.sudo()
        old = lead.lead_owner
        if not old or lead.auto_reassign_count >= self.pool_max_reassigns or lead.is_abroad:
            return False
        # leads created by an incoming call stay with whoever got them
        if lead.leads_source and lead.leads_source.name == 'Incoming Call Leads':
            return False
        Lead = lead.with_context(pool_force=True, pool_exclude_employee_ids=old.ids, skip_pool_rules=True)
        try:
            with self.env.cr.savepoint():
                Lead._auto_assign_lead(Lead)
                self.env.flush_all()
        except Exception as e:  # noqa: BLE001
            _logger.error('Pool reassign of lead %s failed: %s', lead.id, e)
            return False
        lead.invalidate_recordset(['lead_owner'])
        if lead.lead_owner == old or not lead.lead_owner:
            return False
        lead.with_context(skip_pool_rules=True).write({'auto_reassign_count': lead.auto_reassign_count + 1})
        lead.message_post(body=_("Auto-reassigned from %(old)s to %(new)s: %(why)s.") % {
            'old': old.name, 'new': lead.lead_owner.name, 'why': reason})
        self._pool_notify(old, lead.lead_owner, lead, reason)
        return True

    def _pool_notify(self, old, new, lead, reason):
        """Popup (sticky toast) for the officer who lost the lead, and one for the officer who got it."""
        label = '%s%s' % (lead.name or _('Lead'), (' (%s)' % lead.reference_no) if lead.reference_no else '')
        jobs = [
            (old, _('Lead reassigned'), 'danger', _(
                '%(lead)s was taken from you and assigned to %(new)s: %(why)s.') % {
                    'lead': label, 'new': new.name, 'why': reason}),
            (new, _('New lead assigned'), 'warning', _(
                '%(lead)s was reassigned to you from %(old)s.') % {'lead': label, 'old': old.name}),
        ]
        for emp, title, kind, msg in jobs:
            partner = emp.sudo().user_id.partner_id
            if not partner:
                continue
            try:
                self.env['bus.bus'].sudo()._sendone(
                    partner, 'lead_reassign_notice',
                    {'title': title, 'message': msg, 'type': kind, 'lead_id': lead.id, 'open': emp == new})
            except Exception:  # noqa: BLE001 - a notification problem must never block the reassignment
                _logger.exception('Pool reassign popup failed')

    @api.model
    def cron_pool_reassign_uncalled(self):
        """Leads assigned yesterday that did not get the required calls that day go to another officer."""
        rule = self.sudo().search([('active', '=', True)], order='sequence, id', limit=1)
        if not rule or rule.assignment_type != 'attendance_pool' or not rule.pool_uncalled_reassign:
            return
        if not rule._pool_is_open():
            return
        today_start, _end = rule._pool_today_bounds_utc()
        Lead = self.env['leads.logic'].sudo()
        leads = Lead.search([
            ('lead_owner', '!=', False), ('state', '!=', 'lost'),
            ('lead_quality', 'in', list(UNWORKED)),
            ('reassign_date', '>=', today_start - timedelta(days=1)), ('reassign_date', '<', today_start),
            ('auto_reassign_count', '<', rule.pool_max_reassigns),
        ] + ([('leads_source', 'in', rule.pool_source_ids.ids)] if rule.pool_source_ids else []), order='reassign_date asc', limit=200)
        moved = 0
        for lead in leads:
            calls = len(lead.call_log_ids.filtered(lambda c: c.call_time and c.call_time >= lead.reassign_date))
            if calls >= rule.pool_min_daily_calls:
                continue
            if not (rule._pool_eligible() - lead.lead_owner):
                break
            if rule._pool_reassign_lead(lead, _("only %(c)s of %(n)s required calls on the assigned day") % {
                    'c': calls, 'n': rule.pool_min_daily_calls}):
                moved += 1
        if moved:
            _logger.info('Pool: %s uncalled lead(s) reassigned to another officer.', moved)


    @api.model
    def cron_pool_reassign_not_called_quickly(self):
        """A New lead with no call at all `pool_first_call_minutes` after assignment goes to another officer."""
        rules = self.sudo().search([('active', '=', True), ('assignment_type', '=', 'attendance_pool'),
                                    ('pool_first_call_reassign', '=', True)], order='sequence, id')
        Lead = self.env['leads.logic'].sudo()
        for rule in rules:
            if not rule._pool_is_open() or not rule.pool_first_call_minutes:
                continue
            now = fields.Datetime.now()
            limit = now - timedelta(minutes=rule.pool_first_call_minutes)
            leads = Lead.search([
                ('lead_owner', '!=', False), ('state', '!=', 'lost'),
                ('lead_quality', 'in', [False, 'new']),
                ('reassign_date', '>=', now - timedelta(days=1)), ('reassign_date', '<=', limit),
                ('auto_reassign_count', '<', rule.pool_max_reassigns),
            ] + ([('leads_source', 'in', rule.pool_source_ids.ids)] if rule.pool_source_ids else []),
                order='reassign_date asc', limit=100)
            moved = 0
            for lead in leads:
                if lead.call_log_ids.filtered(lambda c: (c.call_time or c.create_date) >= lead.reassign_date):
                    continue
                if not (rule._pool_eligible() - lead.lead_owner):
                    break
                if rule._pool_reassign_lead(lead, _("not called within %s minutes of assignment")
                                            % rule.pool_first_call_minutes):
                    moved += 1
            if moved:
                _logger.info('Pool: %s lead(s) not called in time were reassigned.', moved)


class LeadCallLogPoolRules(models.Model):
    _inherit = 'lead.call.log'

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if not self.env.context.get('otm_odoo17_import'):
            recs._pool_auto_rnr()
            recs._incoming_assign_owner()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if 'call_status' in vals or 'duration' in vals or 'user_id' in vals:
            self._pool_auto_rnr()
            if not self.env.context.get('otm_odoo17_import'):
                self._incoming_assign_owner()
        return res

    def _incoming_assign_owner(self):
        """An incoming call answered by an officer (or a connected call-back to an unowned lead): that officer gets the lead when it is a new
        'Incoming Call Leads' lead or has no owner yet. Leads owned by someone else are left alone."""
        from .call_report import _parse_duration_seconds, _is_connected
        try:
            for log in self.sudo():
                lead, user = log.lead_id, log.user_id
                if not lead or lead.state == 'lost':
                    continue
                # answered incoming call, or a connected call-back (outgoing) on a lead nobody owns yet
                if log.call_type != 'incoming' and not (log.call_type == 'outgoing' and not lead.lead_owner):
                    continue
                if not _is_connected(log.call_status, _parse_duration_seconds(log.duration)):
                    continue
                if not user:
                    _logger.warning('Incoming auto-assign: call %s (lead %s) answered but no officer '
                                    'matched the agent number - check the user\'s Bonvoice/Voxbay number.',
                                    log.id, lead.id)
                    continue
                emp = user.employee_id
                if not emp:
                    _logger.warning('Incoming auto-assign: user %s has no employee - lead %s not assigned.',
                                    user.login, lead.id)
                    continue
                if lead.lead_owner == emp:
                    continue
                incoming_src = lead.leads_source and lead.leads_source.name == 'Incoming Call Leads'
                if lead.lead_owner and not incoming_src:
                    continue
                old = lead.lead_owner
                lead.with_context(skip_pool_rules=True, urgent_lead_skip=True).write({'lead_owner': emp.id})
                lead.message_post(body=_("Incoming call answered by %(new)s: lead assigned to %(new)s%(old)s.") % {
                    'new': emp.name, 'old': (_(' (was %s)') % old.name) if old else ''})
        except Exception:  # noqa: BLE001 - never block call logging
            _logger.exception('Incoming call auto-assign failed')

    def _pool_auto_rnr(self):
        """New / First Attempt lead with N calls and none answered -> Ringing Not Responding."""
        from .call_report import _parse_duration_seconds
        try:
            need = self.env['otm.lead.rule.params'].param('custom_leads_19.rnr_min_calls')
            if not need:
                return
            for lead in self.mapped('lead_id').sudo():
                if lead.lead_quality not in UNWORKED or lead.state == 'lost' or lead.is_abroad:
                    continue
                rule = lead._pool_rule()
                if not rule or not rule.pool_auto_rnr:
                    continue
                calls = lead.call_log_ids.filtered(lambda c: c.call_type != 'incoming')
                if len(calls) < need:
                    continue
                if any(_parse_duration_seconds(c.duration) > 0 for c in lead.call_log_ids):
                    continue
                lead.with_context(skip_pool_rules=True).write({'lead_quality': 'not_responding'})
                lead.message_post(body=_("Set to Ringing Not Responding automatically: %s calls, none answered.")
                                  % len(calls))
        except Exception:  # noqa: BLE001 - never block call logging
            _logger.exception('Pool auto RNR failed')
