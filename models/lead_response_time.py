# -*- coding: utf-8 -*-
"""Lead response-time columns: how long a lead waited to be assigned / first called,
plus a follow-up counter. Stored so the Lead Response report can sort, filter and group."""
from odoo import api, fields, models


def _fmt(hours):
    """2.25 -> '2h 15m' ; 0 -> '0m'."""
    mins = int(round(max(hours, 0.0) * 60))
    h, m = divmod(mins, 60)
    if h and m:
        return '%dh %dm' % (h, m)
    return '%dh' % h if h else '%dm' % m


class LeadsLogicResponse(models.Model):
    _inherit = 'leads.logic'

    followup_count = fields.Integer(string='Follow-ups', compute='_compute_followup_count', store=True)
    first_assigned_dt = fields.Datetime(string='First Assigned On', compute='_compute_response_times', store=True)
    first_called_dt = fields.Datetime(string='First Called On', compute='_compute_response_times', store=True)
    assign_delay_hrs = fields.Float(string='Assign Delay (Hrs)', compute='_compute_response_times', store=True,
                                    aggregator='avg')
    call_delay_hrs = fields.Float(string='Call Delay (Hrs)', compute='_compute_response_times', store=True,
                                  aggregator='avg')
    assigned_after = fields.Char(string='Assigned After', compute='_compute_response_times', store=True)
    called_after = fields.Char(string='Called After', compute='_compute_response_times', store=True)

    @api.depends('followup_ids')
    def _compute_followup_count(self):
        for rec in self:
            rec.followup_count = len(rec.followup_ids)

    @api.depends('create_date', 'assignment_history_ids.assigned_date', 'call_log_ids.call_time')
    def _compute_response_times(self):
        for rec in self:
            created = rec.create_date
            assigned = [d for d in rec.assignment_history_ids.mapped('assigned_date') if d]
            called = [d for d in rec.call_log_ids.mapped('call_time') if d]
            a = min(assigned) if assigned else False
            c = min(called) if called else False
            rec.first_assigned_dt = a
            rec.first_called_dt = c
            if created and a:
                h = (a - created).total_seconds() / 3600.0
                rec.assign_delay_hrs = max(h, 0.0)
                rec.assigned_after = _fmt(h)
            else:
                rec.assign_delay_hrs = 0.0
                rec.assigned_after = 'Not assigned'
            if created and c:
                h = (c - created).total_seconds() / 3600.0
                rec.call_delay_hrs = max(h, 0.0)
                rec.called_after = _fmt(h)
            else:
                rec.call_delay_hrs = 0.0
                rec.called_after = 'Not called yet'
