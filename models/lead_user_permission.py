from odoo import models, fields, api
from odoo.exceptions import AccessError


# Map: field_name → (xml_id, label)
LEAD_GROUP_MAP = {
    'perm_super_admin':   ('custom_leads_19.group_super_admin',        'Super Admin'),
    'perm_manager':       ('custom_leads_19.group_lead_manager',        'Manager'),
    'perm_team_lead':     ('custom_leads_19.group_lead_team_lead',      'Team Lead'),
    'perm_officer':       ('custom_leads_19.group_lead_users',          'Admission Officer'),
    'perm_tele_caller':   ('custom_leads_19.group_lead_tele_callers',   'Tele Caller'),
    'perm_digital_team':  ('custom_leads_19.group_lead_digital_team',   'Digital Team'),
    'perm_digital_head':  ('custom_leads_19.group_lead_digital_head',   'Digital Head'),
    'perm_branch_head':   ('custom_leads_19.group_lead_branch_head',    'Branch Head'),
    'perm_crash_head':    ('custom_leads_19.group_crash_head',          'Crash Head'),
    'perm_crash_user':    ('custom_leads_19.group_crash_user',          'Crash User'),
    'perm_reattempt_user':    ('custom_leads_19.group_reattempt_user',     'Re-Attempt User'),
    'perm_reattempt_tl':      ('custom_leads_19.group_reattempt_teamlead', 'Re-Attempt Team Lead'),
    'perm_reattempt_manager': ('custom_leads_19.group_reattempt_manager',  'Re-Attempt Manager'),
}


class LeadUserPermission(models.Model):
    _name = 'lead.user.permission'
    _description = 'Lead Management User Permission'
    _rec_name = 'user_id'
    _order = 'user_id'

    user_id = fields.Many2one(
        'res.users', string='User', required=True,
        domain=[('share', '=', False)],
        ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        compute='_compute_employee_id', store=True,
    )
    active = fields.Boolean(default=True)
    notes = fields.Char(string='Notes')

    # ── Lead Roles ────────────────────────────────────────────────────
    perm_super_admin   = fields.Boolean(string='Super Admin')
    perm_manager       = fields.Boolean(string='Manager')
    perm_team_lead     = fields.Boolean(string='Team Lead')
    perm_officer       = fields.Boolean(string='Admission Officer')
    perm_tele_caller   = fields.Boolean(string='Tele Caller')
    perm_digital_team  = fields.Boolean(string='Digital Team')
    perm_digital_head  = fields.Boolean(string='Digital Head')
    perm_branch_head   = fields.Boolean(string='Branch Head')
    perm_crash_head    = fields.Boolean(string='Crash Head')
    perm_crash_user    = fields.Boolean(string='Crash User')

    # ── Re-Attempt Roles ──────────────────────────────────────────────
    perm_reattempt_user    = fields.Boolean(string='Re-Attempt User')
    perm_reattempt_tl      = fields.Boolean(string='Re-Attempt Team Lead')
    perm_reattempt_manager = fields.Boolean(string='Re-Attempt Manager')

    # ── Display: current active groups (simple char, no depends on groups_id) ──
    current_groups = fields.Char(
        string='Active Roles',
        compute='_compute_current_groups',
        store=False,
    )

    _sql_constraints = [
        ('unique_user', 'UNIQUE(user_id)',
         'A permission record already exists for this user.'),
    ]

    @api.depends('user_id')
    def _compute_employee_id(self):
        for rec in self:
            emp = self.env['hr.employee'].search(
                [('user_id', '=', rec.user_id.id)], limit=1
            )
            rec.employee_id = emp

    # No depends on groups_id — just read from the boolean fields on this record
    def _compute_current_groups(self):
        for rec in self:
            labels = [
                label
                for fname, (_, label) in LEAD_GROUP_MAP.items()
                if getattr(rec, fname, False)
            ]
            rec.current_groups = ', '.join(labels) if labels else 'No Access'

    # ── Security ──────────────────────────────────────────────────────
    def _check_super_admin(self):
        if not self.env.user.has_group('custom_leads_19.group_super_admin'):
            raise AccessError(
                'Only Super Admin can manage Lead user permissions.'
            )

    @api.model_create_multi
    def create(self, vals_list):
        self._check_super_admin()
        records = super().create(vals_list)
        for rec in records:
            rec._sync_groups()
        return records

    def write(self, vals):
        self._check_super_admin()
        res = super().write(vals)
        perm_fields = set(LEAD_GROUP_MAP.keys())
        if perm_fields & set(vals.keys()):
            for rec in self:
                rec._sync_groups()
        return res

    def unlink(self):
        self._check_super_admin()
        for rec in self:
            rec._remove_all_lead_groups()
        return super().unlink()

    # ── Core: sync boolean fields → Odoo groups ───────────────────────
    def _sync_groups(self):
        """Add/remove each lead group based on the boolean permission fields."""
        self.ensure_one()
        user = self.user_id.sudo()
        to_add = []
        to_remove = []
        for fname, (xml_id, _) in LEAD_GROUP_MAP.items():
            grp = self.env.ref(xml_id, raise_if_not_found=False)
            if not grp:
                continue
            if getattr(self, fname, False):
                to_add.append((4, grp.id))
            else:
                to_remove.append((3, grp.id))
        if to_add or to_remove:
            user.write({'group_ids': to_remove + to_add})

    def _remove_all_lead_groups(self):
        self.ensure_one()
        user = self.user_id.sudo()
        cmds = []
        for fname, (xml_id, _) in LEAD_GROUP_MAP.items():
            grp = self.env.ref(xml_id, raise_if_not_found=False)
            if grp:
                cmds.append((3, grp.id))
        if cmds:
            user.write({'group_ids': cmds})

    # ── Sync booleans FROM actual Odoo groups (for existing users) ────
    def action_sync_from_odoo(self):
        """Pull current Odoo group membership into the boolean fields."""
        self._check_super_admin()
        for rec in self:
            vals = {}
            for fname, (xml_id, _) in LEAD_GROUP_MAP.items():
                grp = self.env.ref(xml_id, raise_if_not_found=False)
                vals[fname] = bool(
                    grp and rec.user_id.has_group(xml_id)
                )
            super(LeadUserPermission, rec).write(vals)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Synced',
                'message': 'Permissions synced from Odoo groups.',
                'type': 'success',
                'sticky': False,
            }
        }

    # ── Apply button ──────────────────────────────────────────────────
    def action_apply(self):
        self._check_super_admin()
        for rec in self:
            rec._sync_groups()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Permission Applied',
                'message': f'Roles updated for {self.user_id.name}.',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_revoke_all(self):
        self._check_super_admin()
        for rec in self:
            rec._remove_all_lead_groups()
            vals = {fname: False for fname in LEAD_GROUP_MAP}
            super(LeadUserPermission, rec).write(vals)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Access Revoked',
                'message': 'All lead roles removed.',
                'type': 'warning',
                'sticky': False,
            }
        }
