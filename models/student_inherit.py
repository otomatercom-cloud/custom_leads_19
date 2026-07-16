from odoo import api, fields, models, _
from odoo.exceptions import UserError


class StudentDetailsInherit(models.Model):
    _inherit = 'student.details'
    _description = 'Student Details (Lead Extension)'

    lead_id = fields.Many2one('leads.logic', string='Source Lead', readonly=True, copy=False)
    lead_ids = fields.One2many('leads.logic', 'student_id', string='Connected Leads', readonly=True)
    lead_count = fields.Integer(string='Leads', compute='_compute_lead_count')

    @api.depends('lead_ids', 'lead_id')
    def _compute_lead_count(self):
        for student in self:
            lead_ids = set(student.lead_ids.ids)
            if student.lead_id:
                lead_ids.add(student.lead_id.id)
            student.lead_count = len(lead_ids)

    def _get_connected_lead_ids(self):
        self.ensure_one()
        lead_ids = set(self.lead_ids.ids)
        if self.lead_id:
            lead_ids.add(self.lead_id.id)
        return list(lead_ids)

    def action_view_leads(self):
        self.ensure_one()
        lead_ids = self._get_connected_lead_ids()
        if not lead_ids:
            raise UserError(_('No leads are linked to this student.'))

        action = self.env.ref('custom_leads_19.action_leads_logic').read()[0]
        if len(lead_ids) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': lead_ids[0],
                'views': [(False, 'form')],
                'domain': [],
            })
        else:
            action['domain'] = [('id', 'in', lead_ids)]
        action['context'] = dict(self.env.context, default_student_id=self.id)
        return action
