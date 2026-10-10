# -*- coding: utf-8 -*-
"""Lead response-time columns: how long a lead waited to be assigned / first called,
plus a follow-up counter. Stored so the Lead Response report can sort, filter and group."""
from odoo import api, fields, models

from .call_report import _fmt_duration, _parse_duration_seconds


def _fmt(hours):
    """Readable duration: 25m, 3h 10m, 2d 5h (24 hours or more is shown in days)."""
    mins = int(round(max(hours, 0.0) * 60))
    d, rest = divmod(mins, 1440)
    h, m = divmod(rest, 60)
    if d:
        return '%dd %dh' % (d, h) if h else '%dd' % d
    if h:
        return '%dh %dm' % (h, m) if m else '%dh' % h
    return '%dm' % m


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

    total_call_seconds = fields.Integer(string='Total Call Seconds', compute='_compute_total_call_duration',
                                        store=True)
    total_call_duration = fields.Char(string='Call Duration', compute='_compute_total_call_duration',
                                      store=True, help='Sum of the duration of every call on this lead (HH:MM:SS).')

    @api.depends('call_log_ids.duration')
    def _compute_total_call_duration(self):
        for rec in self:
            secs = sum(_parse_duration_seconds(c.duration) for c in rec.call_log_ids)
            rec.total_call_seconds = secs
            rec.total_call_duration = _fmt_duration(secs)

    followup_done_count = fields.Integer(string='Follow-ups Done', compute='_compute_followup_done', store=True)
    followup_due_count = fields.Integer(
        string='Follow-ups Due', compute='_compute_followup_due',
        help='Scheduled follow-ups whose date and time has already arrived and are not done yet.')

    @api.depends('followup_ids.status')
    def _compute_followup_done(self):
        for rec in self:
            rec.followup_done_count = len(rec.followup_ids.filtered(lambda f: f.status == 'done'))

    def _compute_followup_due(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.followup_due_count = len(rec.followup_ids.filtered(
                lambda f: f.status == 'scheduled' and f.next_followup_date and f.next_followup_date <= now))

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
