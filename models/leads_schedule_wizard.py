from odoo import models, fields, api


class LeadsScheduleWizard(models.TransientModel):
    _name = "leads.schedule.wizard"
    _description = "Schedule Zoom/Walk-in Wizard"

    lead_id = fields.Many2one('leads.logic', string="Lead", required=True)
    schedule_type = fields.Selection([
        ('zoom', 'Zoom Schedule'),
        ('walkin', 'Walk-in Schedule'),
    ], string="Schedule Type", required=True, default='zoom')
    schedule_date = fields.Datetime(string="Schedule Date & Time", required=True)

    def action_schedule(self):
        self.ensure_one()
        if self.schedule_type == 'zoom':
            self.lead_id.write({'zoom_schedule_dt': self.schedule_date})
            self.lead_id.message_post(body=f"Zoom Meeting Scheduled for {self.schedule_date} by {self.env.user.name}")
        elif self.schedule_type == 'walkin':
            self.lead_id.write({'walkin_schedule_dt': self.schedule_date})
            self.lead_id.message_post(body=f"Walk-in Scheduled for {self.schedule_date} by {self.env.user.name}")
        return {'type': 'ir.actions.act_window_close'}
