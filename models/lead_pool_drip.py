# -*- coding: utf-8 -*-
"""Pool "slot" (drip) mode.

Leads that arrive in the evening / night / early morning wait in the pool. When the pool opens, every eligible
admission officer gets only N leads (default 2). As soon as an officer starts calling one of them (or changes
its quality) a slot is free and the next waiting lead is given to the officer with the fewest untouched leads.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LeadAssignmentRuleDrip(models.Model):
    _inherit = 'lead.assignment.rule'

    pool_drip = fields.Boolean(
        string='Slot mode: give leads a few at a time', tracking=True,
        help='Waiting leads (evening / night / morning) are not shared all at once when the pool opens. Each '
             'officer gets only the number of leads below; when the officer starts calling one, the next waiting '
             'lead is given.')
    pool_drip_size = fields.Integer(
        string='Untouched leads per officer', default=2,
        help='How many leads an officer can hold without calling them. Calling a lead (or changing its quality) '
             'frees a slot and the next waiting lead is given.')
    pool_app_grace_min = fields.Integer(
        string='Extra minutes for company-phone (app) users', default=20,
        help='Calls made from the company phone reach Odoo a few minutes after the call (the app syncs in the '
             'background). These officers get this many extra minutes before a lead is taken back for "not called".')

    # ---- capacity ---------------------------------------------------------------------------------
    def _pool_drip_untouched(self, employees):
        """{employee id: leads given today that the officer has not called / worked yet}."""
        self.ensure_one()
        start, _end = self._pool_today_bounds_utc()
        res = {e.id: 0 for e in employees}
        if not employees:
            return res
        for emp, n in self.env['leads.logic'].sudo()._read_group(
                [('lead_owner', 'in', employees.ids), ('state', '!=', 'lost'),
                 ('lead_quality', 'in', [False, 'new']), ('first_called_dt', '=', False),
                 ('is_hiring', '=', False), ('is_abroad', '=', False), ('reassign_date', '>=', start)],
                ['lead_owner'], ['__count']):
            res[emp.id] = n
        return res

    def _pool_drip_free(self, exclude=()):
        """(officers with a free slot, {employee id: untouched count})."""
        self.ensure_one()
        eligible = self._pool_eligible().filtered(lambda e: e.id not in (exclude or ()))
        cnt = self._pool_drip_untouched(eligible)
        size = max(1, self.pool_drip_size or 1)
        return eligible.filtered(lambda e: cnt[e.id] < size), cnt

    def _pool_has_capacity(self):
        self.ensure_one()
        if self.pool_drip:
            return bool(self._pool_drip_free()[0])
        return super()._pool_has_capacity()

    def _assign_pool(self, lead):
        if not self.pool_drip:
            return super()._assign_pool(lead)
        if not self._pool_accepts(lead):
            return False, False
        free, cnt = self._pool_drip_free(self.env.context.get('pool_exclude_employee_ids') or ())
        if not free:
            return False, False                      # the lead waits in the pool for a free slot
        low = min(cnt[e.id] for e in free)
        employee = self._pool_pick(free.filtered(lambda e: cnt[e.id] == low))
        team = self.env['lead.team.member'].search([('employee_id', '=', employee.id)], limit=1).team_id
        if not team:
            team = self.env['lead.team'].search([('team_lead_ids', 'in', employee.id)], limit=1)
        return team, employee

    # ---- triggers ---------------------------------------------------------------------------------
    @api.model
    def cron_pool_drip(self):
        """Every 2 minutes: officers who worked a lead get the next waiting one."""
        for rule in self.search([('active', '=', True), ('assignment_type', '=', 'attendance_pool'),
                                 ('pool_drip', '=', True)], order='sequence, id'):
            try:
                n = rule.run_pool()
                if n:
                    _logger.info('Pool slot mode (%s): gave %s waiting lead(s).', rule.name, n)
                    self.env.cr.commit()
            except Exception:  # noqa: BLE001
                self.env.cr.rollback()
                _logger.exception('Pool slot mode failed')


class LeadCallLogDrip(models.Model):
    _inherit = 'lead.call.log'

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if not self.env.context.get('otm_odoo17_import') and any(r.call_type != 'incoming' for r in recs):
            try:
                with self.env.cr.savepoint():
                    for rule in self.env['lead.assignment.rule'].sudo().search([
                            ('active', '=', True), ('assignment_type', '=', 'attendance_pool'),
                            ('pool_drip', '=', True)]):
                        rule.run_pool()
            except Exception:  # noqa: BLE001 - never block call logging
                _logger.exception('Pool slot top-up after call failed')
        return recs
