from odoo import models, fields


class VoxbayCallWizard(models.TransientModel):
    _name = 'voxbay.call.wizard'
    _description = 'Call Status Wizard'

    lead_id = fields.Many2one('leads.logic', string='Lead', required=True)
    phone_number = fields.Char(string='Phone Number', related='lead_id.phone_number', readonly=True)
    api_response = fields.Text(string='API Response', readonly=True)
    call_log_id = fields.Many2one('lead.call.log', string='Call Log')

    def action_completed(self):
        if self.call_log_id:
            self.call_log_id.remarks = "Completed"
        self.lead_id.message_post(body=f"✅ Call with {self.phone_number} logged as: Completed")
        return {'type': 'ir.actions.act_window_close'}

    def action_not_answered(self):
        if self.call_log_id:
            self.call_log_id.remarks = "Not Answered"
        self.lead_id.message_post(body=f"❌ Call with {self.phone_number} logged as: Not Answered")
        return {'type': 'ir.actions.act_window_close'}

    def action_disconnect(self):
        if self.call_log_id:
            self.call_log_id.remarks = "Disconnected"
        self.lead_id.message_post(body=f"🔇 Call with {self.phone_number} logged as: Disconnected")
        return {'type': 'ir.actions.act_window_close'}
