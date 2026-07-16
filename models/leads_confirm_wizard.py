from odoo import models, fields, api


class LeadsConfirmWizard(models.TransientModel):
    _name = "leads.confirm.wizard"
    _description = "Lead Confirm Wizard"

    lead_id = fields.Many2one("leads.logic", string="Lead", required=True)
    name = fields.Char(string="Lead Name", readonly=True)
    phone_number = fields.Char(string="Mobile Number", readonly=True)
    lead_quality = fields.Char(string="Lead Quality", readonly=True)

    first_call_dt = fields.Datetime(string="First Attempt", readonly=True)
    whatsapp_intro = fields.Boolean(copy=False)
    whatsapp_date = fields.Datetime(string="WhatsApp Intro", readonly=True)
    testimonials = fields.Boolean(copy=False)
    testimonials_dt = fields.Datetime(string="Testimonials", readonly=True)
    results_highlights = fields.Boolean(copy=False)
    results_highlights_dt = fields.Datetime(string="Results", readonly=True)
    second_follow_up = fields.Boolean(copy=False)
    second_follow_up_dt = fields.Datetime(string="Second Follow Up", readonly=True)
    sent_webinar = fields.Boolean(copy=False)
    sent_webinar_dt = fields.Datetime(string="Webinar", readonly=True)
    third_call = fields.Boolean(copy=False)
    third_call_dt = fields.Datetime(string="Third Call", readonly=True)
    touches_complete = fields.Boolean(copy=False)
    touches_complete_dt = fields.Datetime(string="Touches Complete", readonly=True)
    zoom_schedule_dt = fields.Datetime(string="Zoom Schedule Date", readonly=True)
    walkin_schedule_dt = fields.Datetime(string="Walk-in Schedule Date", readonly=True)

    lead_owner_id = fields.Many2one('hr.employee', string="Lead Owner", readonly=True)
    created_by_id = fields.Many2one('res.users', string="Created By", readonly=True)
    today_followup_message = fields.Text(string="Today's Follow-up Message", readonly=True)
    team_lead_remarks = fields.Text(string="Team Lead Remarks")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        global_remarks = self.env['ir.config_parameter'].sudo().get_param(
            'custom_leads_19.global_team_lead_remarks', default='')
        res.update({'team_lead_remarks': global_remarks})

        if self.env.context.get('default_lead_id'):
            lead = self.env['leads.logic'].browse(self.env.context['default_lead_id'])
            if lead.exists():
                res.update({
                    'name': lead.name,
                    'phone_number': lead.phone_number,
                    'lead_quality': lead.lead_quality,
                    'lead_owner_id': lead.lead_owner.id,
                    'created_by_id': lead.lead_creator_id.id or lead.create_uid.id,
                    'first_call_dt': lead.first_call_dt,
                    'whatsapp_intro': lead.whatsapp_intro,
                    'whatsapp_date': lead.whatsapp_date,
                    'testimonials': lead.testimonials,
                    'testimonials_dt': lead.testimonials_dt,
                    'results_highlights': lead.results_highlights,
                    'zoom_schedule_dt': lead.zoom_schedule_dt,
                    'walkin_schedule_dt': lead.walkin_schedule_dt,
                })
                today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                today_end = fields.Datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
                followups = self.env['lead.followup'].sudo().search([
                    ('user_id', '=', self.env.user.id),
                    ('status', '=', 'scheduled'),
                    ('next_followup_date', '>=', today_start),
                    ('next_followup_date', '<=', today_end),
                ])
                if followups:
                    msgs = [f"⏰ [{f.next_followup_date.strftime('%H:%M')}] {f.remarks or 'No Remarks'} (Lead: {f.lead_id.name or 'Unknown'})"
                            for f in followups]
                    res['today_followup_message'] = "\n".join(msgs)
        return res

    def action_confirm(self):
        self.ensure_one()
        self.env['lead.open.history'].create({
            'lead_id': self.lead_id.id,
            'user_id': self.env.user.id,
            'remarks': 'Lead opened from confirm wizard',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'leads.logic',
            'res_id': self.lead_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}

    def action_schedule_meeting(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Schedule Meeting',
            'res_model': 'leads.schedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.lead_id.id},
        }

    def action_save_remarks(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'custom_leads_19.global_team_lead_remarks', self.team_lead_remarks or '')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'Global Team Message Updated!',
                'type': 'success',
                'sticky': False,
            }
        }
