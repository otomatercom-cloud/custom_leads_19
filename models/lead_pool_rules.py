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

    def _pool_rule(self):
        rule = self.env['lead.assignment.rule'].sudo().search(
            [('active', '=', True)], order='sequence, id', limit=1)
        return rule if rule and rule.assignment_type == 'attendance_pool' else False

    def write(self, vals):
        reassign = self.env['leads.logic']
        rule = False
        if 'lead_quality' in vals and not self.env.context.get('skip_pool_rules') and not self.env.su:
            rule = self._pool_rule()
        if rule:
            new_q = vals.get('lead_quality')
            need = rule.pool_rnr_min_calls
            if need and new_q == 'not_responding':
                for rec in self:
                    if rec.lead_quality != 'not_responding' and rec.call_count < need:
                        raise UserError(_(
                            "'Ringing Not Responding' needs at least %(need)s calls and this lead has "
                            "only %(have)s. Call the lead again first.") % {'need': need, 'have': rec.call_count})
            mode = rule.pool_reassign_on_quality
            if mode in ('no_call', 'always') and new_q and new_q != 'new':
                for rec in self:
                    if (rec.lead_quality in (False, 'new') and rec.lead_owner
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
        if not old or lead.auto_reassign_count >= self.pool_max_reassigns:
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
                    partner, 'simple_notification', {'title': title, 'message': msg, 'type': kind, 'sticky': True})
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
        ], order='reassign_date asc', limit=200)
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
