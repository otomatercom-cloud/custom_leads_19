from odoo import models, fields, api, _
from odoo.exceptions import UserError


class LeadBulkAssignWizard(models.TransientModel):
    _name = 'lead.bulk.assign.wizard'
    _description = 'Bulk Assign Leads'

    lead_ids = fields.Many2many(
        'leads.logic',
        string='Leads',
        readonly=True,
    )
    lead_count = fields.Integer(
        string='Selected Leads',
        compute='_compute_lead_count',
    )
    new_owner_id = fields.Many2one(
        'hr.employee',
        string='Assign To',
    )

    @api.depends('lead_ids')
    def _compute_lead_count(self):
        for rec in self:
            rec.lead_count = len(rec.lead_ids)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids') or []
        if active_ids:
            res['lead_ids'] = [(6, 0, active_ids)]
        return res

    def action_open_wizard(self):
        """Called from server action — passes active_ids via context to default_get."""
        return {
            'name': _('Bulk Assign Leads'),
            'type': 'ir.actions.act_window',
            'res_model': 'lead.bulk.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_ids': self.env.context.get('active_ids', []),
            },
        }

    def action_bulk_assign(self):
        self.ensure_one()
        if not self.lead_ids:
            raise UserError(_('No leads selected. Please close and select leads from the list first.'))
        if not self.new_owner_id:
            raise UserError(_('Please select an employee to assign the leads to.'))
        self.lead_ids.write({'lead_owner': self.new_owner_id.id})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bulk Assignment Done'),
                'message': _('%d lead(s) assigned to %s.') % (
                    len(self.lead_ids), self.new_owner_id.name
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
