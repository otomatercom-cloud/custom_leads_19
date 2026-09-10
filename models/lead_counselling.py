from odoo import models, fields, api, _
from odoo.exceptions import UserError


class LeadCounselling(models.Model):
    """A single counselling session/appointment against a lead — covers
    scheduled appointments, walk-ins, and phone/video counselling, with
    the student's requirement, course recommendation, outcome, next
    follow-up, and optional parent-counselling details in one record.
    Counsellor Performance (menu) is just this model grouped/pivoted by
    counsellor_id — no separate reporting model needed."""
    _name = 'lead.counselling'
    _description = 'Counselling Session'
    _order = 'appointment_date desc'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name', store=True)
    lead_id = fields.Many2one('leads.logic', string='Lead', required=True,
                              index=True, ondelete='cascade')
    lead_reference = fields.Char(related='lead_id.reference_no', string='Lead Reference', readonly=True)
    phone_number = fields.Char(related='lead_id.phone_number', string='Phone', readonly=True)

    counsellor_id = fields.Many2one('res.users', string='Counsellor',
                                    default=lambda self: self.env.user, required=True)
    mode = fields.Selection([
        ('appointment', 'Scheduled Appointment'),
        ('walk_in', 'Walk-in'),
        ('phone_video', 'Phone / Video'),
    ], string='Mode', default='appointment', required=True)
    appointment_date = fields.Datetime(string='Appointment Date', required=True,
                                       default=lambda self: fields.Datetime.now())
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('done', 'Done'),
        ('no_show', 'No Show'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='scheduled', required=True)

    student_requirement = fields.Text(string='Student Requirement / Interest')
    recommended_course_ids = fields.Many2many('course.interested', string='Recommended Courses')
    remarks = fields.Text(string='Counselling Remarks')
    outcome = fields.Selection([
        ('interested', 'Interested'),
        ('admission_confirmed', 'Admission Confirmed'),
        ('needs_followup', 'Needs Follow-up'),
        ('not_interested', 'Not Interested'),
    ], string='Outcome')
    next_followup_date = fields.Datetime(string='Next Follow-Up Date')

    parent_present = fields.Boolean(string='Parent Counselling')
    parent_name = fields.Char(string='Parent Name')
    parent_phone = fields.Char(string='Parent Phone')

    @api.depends('lead_id.name', 'appointment_date', 'counsellor_id.name')
    def _compute_display_name(self):
        for rec in self:
            date_str = fields.Datetime.to_string(rec.appointment_date)[:16] if rec.appointment_date else ''
            rec.display_name = _('%(lead)s – %(date)s', lead=rec.lead_id.name or '', date=date_str)

    def action_mark_done(self):
        self.write({'state': 'done'})

    def action_mark_no_show(self):
        self.write({'state': 'no_show'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_open_lead(self):
        self.ensure_one()
        if not self.lead_id:
            raise UserError(_("No lead linked to this counselling session."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lead'),
            'res_model': 'leads.logic',
            'view_mode': 'form',
            'res_id': self.lead_id.id,
        }
