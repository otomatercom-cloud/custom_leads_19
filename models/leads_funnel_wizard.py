from odoo import models, fields, api


class LeadsFunnelWizard(models.TransientModel):
    _name = 'leads.funnel.wizard'
    _description = 'Lead Funnel Wizard'

    lead_id = fields.Many2one('leads.logic', string='Lead', required=True)
    first_call = fields.Boolean(related='lead_id.first_call', string="First Call Done")
    whatsapp_intro = fields.Boolean(related='lead_id.whatsapp_intro', string="WhatsApp Sent")
    second_followup = fields.Boolean(related='lead_id.second_followup', string="Second Follow Up Done")
    course_wise_webinar = fields.Boolean(related='lead_id.course_wise_webinar', string="Webinar Done")
    testimonials = fields.Boolean(related='lead_id.testimonials', string="Testimonials Sent")

    def _reload_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lead Funnel',
            'res_model': 'leads.funnel.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': self.env.context,
        }

    def action_first_attempt(self):
        self.ensure_one()
        self.lead_id.write({'first_call': True, 'first_call_dt': fields.Datetime.now(), 'lead_quality': 'first_attempt', 'state': 'in_progress'})
        self.lead_id.message_post(body=f"First Attempt clicked by {self.env.user.name}")
        return self._reload_wizard()

    def action_whatsapp(self):
        self.ensure_one()
        self.lead_id.action_send_whatsapp_intro()
        return self._reload_wizard()

    def action_second_followup(self):
        self.ensure_one()
        self.lead_id.write({'second_followup': True, 'second_followup_dt': fields.Datetime.now()})
        self.lead_id.message_post(body=f"Second Follow Up clicked by {self.env.user.name}")
        return self._reload_wizard()

    def action_course_wise_webinar(self):
        self.ensure_one()
        self.lead_id.write({'course_wise_webinar': True, 'course_wise_webinar_dt': fields.Datetime.now()})
        self.lead_id.message_post(body=f"Course Wise Webinar clicked by {self.env.user.name}")
        return self._reload_wizard()

    def action_testimonials(self):
        self.ensure_one()
        self.lead_id.write({'testimonials': True, 'testimonials_dt': fields.Datetime.now()})
        self.lead_id.message_post(body=f"Testimonials clicked by {self.env.user.name}")
        return self._reload_wizard()

    def action_bypass(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lead Details',
            'res_model': 'leads.logic',
            'view_mode': 'form',
            'res_id': self.lead_id.id,
            'target': 'current',
        }
