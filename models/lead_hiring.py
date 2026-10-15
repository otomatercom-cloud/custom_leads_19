# -*- coding: utf-8 -*-
"""Hiring leads: a Source Campaign whose name contains "hiring" is a job-applicant campaign. Its leads are not
admission leads - they never go to Admission Officers (no auto-assignment, pool, top-up or reassignment); they go to
the HR Assistant group and appear only in the Hiring menu."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class LeadSourceCampaignHiring(models.Model):
    _inherit = 'lead.source.campaign'

    is_hiring = fields.Boolean(
        string='Hiring campaign', default=False, index=True,
        help='Leads of this campaign are job applicants: they go to the HR Assistant, not to Admission Officers. '
             'Ticked automatically when the campaign name contains "hiring".')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'is_hiring' not in vals and 'hiring' in (vals.get('name') or '').lower():
                vals['is_hiring'] = True
        return super().create(vals_list)

    def write(self, vals):
        if 'name' in vals and 'is_hiring' not in vals and 'hiring' in (vals.get('name') or '').lower():
            vals = dict(vals, is_hiring=True)
        return super().write(vals)


class LeadsLogicHiring(models.Model):
    _inherit = 'leads.logic'

    is_hiring = fields.Boolean(string='Hiring lead', related='source_campaign_id.is_hiring', store=True,
                               index=True, readonly=True)

    def _hiring_employees(self):
        group = self.env.ref('custom_leads_19.group_lead_hr_assistant', raise_if_not_found=False)
        if not group:
            return self.env['hr.employee']
        users = self.env['res.users'].sudo().search([('group_ids', 'in', group.id)])
        return users.mapped('employee_id')

    def _assign_hiring_lead(self, lead):
        """Give the lead to the HR Assistant who holds the fewest hiring leads (does nothing if there is none)."""
        emps = self._hiring_employees()
        if not emps:
            return False
        counts = {}
        for emp, n in self.env['leads.logic'].sudo()._read_group(
                [('is_hiring', '=', True), ('lead_owner', 'in', emps.ids)], ['lead_owner'], ['__count']):
            counts[emp.id] = n
        emp = min(emps, key=lambda e: (counts.get(e.id, 0), e.id))
        lead = lead.sudo()
        old = lead.lead_owner
        lead.with_context(skip_assignment_history=True).write({
            'lead_owner': emp.id, 'assigned_date': fields.Date.today()})
        self.env['lead.assignment.history'].sudo().create({
            'lead_id': lead.id, 'owner_id': emp.id, 'new_owner_id': emp.id,
            'old_owner_id': old.id if old else False,
            'changed_by': self.env.uid, 'assigned_date': fields.Datetime.now(), 'assigned_by': self.env.uid})
        return True

    def _auto_assign_lead(self, lead):
        if lead.is_hiring:
            return self._assign_hiring_lead(lead)
        return super()._auto_assign_lead(lead)

    def action_assign_hiring(self):
        """List action (Manager / Super Admin): send the selected hiring leads to the HR Assistant."""
        leads = self.filtered('is_hiring')
        done = sum(1 for lead in leads if self._assign_hiring_lead(lead))
        msg = _('%s hiring lead(s) assigned to the HR Assistant.') % done if done else \
            _('Nothing assigned: select hiring leads, and make sure someone is in the HR Assistant group.')
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Hiring'), 'message': msg, 'type': 'success' if done else 'warning'}}


class LeadsLogicReassignGuard(models.Model):
    """Changing the Lead Owner by hand (form / list edit) is for Team Leads, Managers and Super Admins only.
    Only the screen save (web_save) is checked, so auto-assignment, the pool, top-up, imports and the bulk
    assign wizards are not affected."""
    _inherit = 'leads.logic'

    can_reassign = fields.Boolean(compute='_compute_can_reassign')

    def _user_can_reassign(self):
        u = self.env.user
        return (u._is_superuser() or u.has_group('custom_leads_19.group_lead_team_lead')
                or u.has_group('custom_leads_19.group_lead_manager')
                or u.has_group('custom_leads_19.group_super_admin'))

    def _compute_can_reassign(self):
        ok = self._user_can_reassign()
        for rec in self:
            rec.can_reassign = ok

    def web_save(self, vals, *args, **kwargs):
        if self and 'lead_owner' in vals and not self._user_can_reassign():
            new = vals.get('lead_owner') or False
            if any((rec.lead_owner.id or False) != new for rec in self):
                raise UserError(_('Only a Team Lead or Manager can reassign a lead to another officer.'))
        return super().web_save(vals, *args, **kwargs)
