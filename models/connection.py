from odoo import fields, models, api, _, tools
from odoo.exceptions import ValidationError, UserError
from datetime import datetime


class ConnectionForm(models.TransientModel):
    _name = 'connect.form'
    _description = 'Connection Form'

    lead_quality = fields.Selection(
        [
            ('hot', 'Hot'), ('warm', 'Warm'), ('cold', 'Cold'),
            ('not_responding', 'Not Responding'),
        ],
        string='Lead Quality'
    )
    expected_joining_date = fields.Date(string="Expected Joining Date")
    lead_id = fields.Many2one('leads.logic', string="Lead")
    subject = fields.Many2one('mail.activity.type', string="Subject")
    task_owner_id = fields.Many2one('res.users', string="Task Owner")
    due_date = fields.Date(string="Due Date")
    status = fields.Selection(
        [
            ('not_started', 'Not Started'), ('deferred', 'Deferred'),
            ('in_progress', 'In Progress'), ('completed', 'Completed'),
            ('waiting_for_input', 'Waiting for Input'),
        ],
        string='Status'
    )
    priority = fields.Selection(
        [('high', 'High'), ('highest', 'Highest'), ('low', 'Low'), ('lowest', 'Lowest'), ('normal', 'Normal')],
        string='Priority'
    )
    description = fields.Text(string="Description")
    date = fields.Datetime(string="Date Time")

    @api.onchange('lead_quality')
    def _onchange_lead_quality(self):
        if self.lead_quality:
            if self.lead_quality not in ('warm', 'hot'):
                self.expected_joining_date = False

    def act_connect(self):
        self.lead_id.write({
            'lead_quality': self.lead_quality,
            'expected_joining_date': self.expected_joining_date,
            'current_status': 'need_follow_up',
            'state': 'in_progress',
            'call_response': self.description,
            'next_follow_up_date': self.due_date
        })
        if self.task_owner_id and self.subject and self.due_date:
            self.lead_id.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=self.task_owner_id.id,
                summary=self.description,
                activity_type_id=self.subject.id,
                date_deadline=self.due_date,
                note='Task Created.'
            )


class NotConnectionForm(models.TransientModel):
    _name = 'not.connect.form'

    notes = fields.Text(string="Notes")
    lead_id = fields.Many2one('leads.logic', string="Lead")

    def act_done(self):
        self.lead_id.write({
            'not_response_note': self.notes,
            'lead_quality': 'not_responding',
            'current_status': 'not_responding',
        })


class ConvertLead(models.TransientModel):
    _name = 'convert.lead'

    amount = fields.Float(string="Booking Amount")
    lead_id = fields.Many2one('leads.logic', string="Deal Name")
    closing_date = fields.Date(string="Closing Date")
    lead_owner_id = fields.Many2one('res.users', string="Lead Owner")

    def act_convert(self):
        self.lead_id.write({
            'closing_date': self.closing_date,
            'lead_quality': 'waiting_for_admission',
            'booking_amount': self.amount,
            'state': 'in_progress',
            'current_status': 'need_follow_up',
        })


class LostLead(models.TransientModel):
    _name = 'lost.lead.form'

    lead_id = fields.Many2one('leads.logic', string="Lead")
    reason = fields.Text(string="Lost Reason")

    @api.constrains('reason')
    def _check_reason(self):
        for record in self:
            if not record.reason:
                raise ValidationError("Reason is required.")
            if len(record.reason) < 10:
                raise ValidationError("Reason must be at least 10 characters long.")

    def act_lost_lead(self):
        self.lead_id.write({
            'state': 'lost',
            'lost_reason': self.reason,
            'current_status': 'lost',
            'updated_remarks': self.reason
        })
