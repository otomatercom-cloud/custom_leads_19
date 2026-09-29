from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .lead_user_permission import LEAD_GROUP_MAP


class LeadUserPermissionBulkWizard(models.TransientModel):
    _name = 'lead.user.permission.bulk.wizard'
    _description = 'Bulk Lead User Permissions'

    user_ids = fields.Many2many(
        'res.users', 'lead_perm_bulk_wiz_user_rel', 'wizard_id', 'user_id',
        string='Users', domain=[('share', '=', False)])
    mode = fields.Selection(
        [('add', 'Add selected roles (keep existing roles)'),
         ('replace', 'Replace roles (users get exactly the selected roles)'),
         ('remove', 'Remove selected roles')],
        string='Action', default='add', required=True)

    perm_super_admin = fields.Boolean(string='Super Admin')
    perm_manager = fields.Boolean(string='Manager')
    perm_team_lead = fields.Boolean(string='Team Lead')
    perm_officer = fields.Boolean(string='Admission Officer')
    perm_tele_caller = fields.Boolean(string='Tele Caller')
    perm_digital_team = fields.Boolean(string='Digital Team')
    perm_digital_head = fields.Boolean(string='Digital Head')
    perm_branch_head = fields.Boolean(string='Branch Head')
    perm_crash_head = fields.Boolean(string='Crash Head')
    perm_crash_user = fields.Boolean(string='Crash User')
    perm_reattempt_user = fields.Boolean(string='Re-Attempt User')
    perm_reattempt_tl = fields.Boolean(string='Re-Attempt Team Lead')
    perm_reattempt_manager = fields.Boolean(string='Re-Attempt Manager')

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('custom_leads_19.group_super_admin'):
            raise UserError(_('Only Super Admin can manage Lead user permissions.'))
        if not self.user_ids:
            raise UserError(_('Select at least one user.'))
        selected = [f for f in LEAD_GROUP_MAP if self[f]]
        if not selected and self.mode != 'replace':
            raise UserError(_('Tick at least one role.'))

        Perm = self.env['lead.user.permission'].with_context(active_test=False)
        for user in self.user_ids:
            rec = Perm.search([('user_id', '=', user.id)], limit=1)
            if not rec:
                # start from the roles the user really has, so nothing is silently stripped
                initial = {f: bool(user.has_group(xml)) for f, (xml, _l) in LEAD_GROUP_MAP.items()
                           if self.env.ref(xml, raise_if_not_found=False)}
                rec = Perm.create(dict(initial, user_id=user.id))
            vals = {}
            for f in LEAD_GROUP_MAP:
                if self.mode == 'add' and self[f]:
                    vals[f] = True
                elif self.mode == 'remove' and self[f]:
                    vals[f] = False
                elif self.mode == 'replace':
                    vals[f] = bool(self[f])
            if vals:
                rec.write(vals)   # write() syncs the Odoo groups
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Permissions Updated'),
                       'message': _('%d user(s) updated.') % len(self.user_ids),
                       'type': 'success', 'sticky': False,
                       'next': {'type': 'ir.actions.act_window_close'}},
        }
