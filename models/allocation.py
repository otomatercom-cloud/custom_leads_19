from odoo import fields, models, api, _


class AllocationTeleCallersWizard(models.TransientModel):
    _name = 'allocation.tele_callers.wizard'
    _description = 'Allocation'

    assign_to = fields.Many2one('res.users', string='Telecaller')

    def action_add_assigned_user(self):
        parent_ids = self.env.context.get('parent_obj', [])
        if not parent_ids:
            return
        leads = self.env['leads.logic'].sudo().search([('id', 'in', parent_ids)])
        for rec in leads:
            rec.sudo().write({
                'tele_caller_id': self.assign_to.id,
                'assigned_date': fields.Datetime.now(),
            })

    def action_add_assign_to_lead_owner(self):
        parent_ids = self.env.context.get('parent_obj', [])
        if not parent_ids:
            return
        leads = self.env['leads.logic'].sudo().search([('id', 'in', parent_ids)])
        for rec in leads:
            rec.sudo().write({
                'lead_owner': self.assign_to.employee_id.id,
                'assigned_date': fields.Datetime.now(),
            })


class ReAllocationLeads(models.TransientModel):
    _name = 're.allocation.leads'
    _description = "Re Allocation Leads Wizard"

    lead_owner_id = fields.Many2one('res.users', string="Lead Owner")
    leads_ids = fields.Many2many('leads.logic', string="Leads")

    def act_re_allocation(self):
        for i in self.leads_ids:
            i.lead_owner = i.lead_owner_id.employee_id.id
            i.re_allocation_date = fields.Datetime.now()
            i.message_post(body=f"Lead re-allocated to {self.lead_owner_id.employee_id.name}")
