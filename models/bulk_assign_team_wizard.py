import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BulkAssignTeamWizard(models.TransientModel):
    """
    Bulk-assign selected leads (from the leads list view) to a team.

    Since `leads.logic.team_id` is computed from `lead_owner`'s team
    membership, "assigning to a team" really means picking the right
    `hr.employee` within that team for each lead. Two modes are offered:
      - round_robin:      distribute leads evenly across the team's
                           members, using the SAME DB-safe counter the
                           automatic assignment engine uses, so manual
                           bulk assignment stays in sync with it.
      - specific_member:  assign every selected lead to one chosen member.
    """
    _name = 'bulk.assign.team.wizard'
    _description = 'Bulk Assign Leads to Team'

    lead_ids = fields.Many2many(
        'leads.logic',
        string='Leads',
        default=lambda self: self.env.context.get('active_ids', []),
    )
    lead_count = fields.Integer(string='Selected Leads', compute='_compute_lead_count')

    team_id = fields.Many2one(
        'lead.team',
        string='Team',
        required=True,
        domain="[('active', '=', True)]",
        help='Selected leads will be assigned to members of this team.',
    )
    include_team_leads = fields.Boolean(
        string='Include Team Leads',
        help='If enabled, team leads also participate in the round-robin distribution.',
    )
    assign_mode = fields.Selection([
        ('round_robin', 'Distribute Evenly (Round Robin)'),
        ('specific_member', 'Assign All to One Member'),
    ], string='Assignment Mode', default='round_robin', required=True)

    team_member_ids = fields.Many2many(
        'hr.employee',
        string='Eligible Members',
        compute='_compute_team_member_ids',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Assign To',
        domain="[('id', 'in', team_member_ids)]",
        help='Used only when Assignment Mode is "Assign All to One Member".',
    )

    @api.depends('lead_ids')
    def _compute_lead_count(self):
        for wiz in self:
            wiz.lead_count = len(wiz.lead_ids)

    @api.depends('team_id', 'include_team_leads')
    def _compute_team_member_ids(self):
        for wiz in self:
            employees = wiz.team_id.member_ids.mapped('employee_id').filtered(
                lambda e: e.user_id and e.user_id.active
            )
            if wiz.include_team_leads:
                employees |= wiz.team_id.team_lead_ids.filtered(
                    lambda e: e.user_id and e.user_id.active
                )
            wiz.team_member_ids = employees

    @api.onchange('team_id', 'assign_mode', 'include_team_leads')
    def _onchange_reset_employee(self):
        # Avoid keeping a stale employee_id selected from a previous team
        self.employee_id = False

    def action_assign(self):
        self.ensure_one()

        leads = self.lead_ids or self.env['leads.logic'].browse(
            self.env.context.get('active_ids', [])
        )
        if not leads:
            raise UserError(_('No leads selected. Select leads from the list view first.'))

        if not self.team_member_ids:
            raise UserError(_(
                'Team "%(team)s" has no eligible members (with an active user account). '
                'Add members to the team first.',
                team=self.team_id.name,
            ))

        if self.assign_mode == 'specific_member' and not self.employee_id:
            raise UserError(_('Please select which team member to assign all leads to.'))

        assigned_count = 0
        skipped_count = 0

        virtual_rule = None
        if self.assign_mode == 'round_robin':
            # Reuse the assignment engine's own DB-safe round-robin counter
            # (keyed by team, not by rule), so this stays in sync with
            # automatic assignment for the same team.
            virtual_rule = self.env['lead.assignment.rule'].new({
                'include_team_leads': self.include_team_leads,
            })

        for lead in leads:
            employee = False
            try:
                # Each lead gets its own SQL savepoint. If the round-robin
                # pick or the write fails for any reason, we roll back just
                # this savepoint (not the whole transaction) and move on —
                # otherwise one bad lead poisons the entire batch and every
                # later statement, including the final flush, fails with an
                # opaque "transaction is aborted" error.
                with self.env.cr.savepoint():
                    if self.assign_mode == 'specific_member':
                        employee = self.employee_id
                    else:
                        employee = virtual_rule._round_robin_member(self.team_id)

                    if employee:
                        lead.write({'lead_owner': employee.id})
                        # Flush now, inside the savepoint, so any DB-level
                        # error (constraint violation, etc.) surfaces here
                        # and gets isolated, instead of being deferred to
                        # the end-of-request flush where it's hard to trace.
                        self.env.flush_all()
            except Exception as e:
                _logger.error(
                    'Bulk Assign to Team: failed to assign lead %s (id=%s): %s',
                    lead.display_name, lead.id, str(e),
                )
                employee = False

            if employee:
                assigned_count += 1
            else:
                skipped_count += 1

        if assigned_count:
            message = _(
                '%(count)s lead(s) assigned to team "%(team)s".',
                count=assigned_count, team=self.team_id.name,
            )
            if skipped_count:
                message += ' ' + _('%(skipped)s lead(s) were skipped.', skipped=skipped_count)
            msg_type = 'success'
        else:
            message = _('No leads could be assigned.')
            msg_type = 'warning'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bulk Team Assignment'),
                'message': message,
                'type': msg_type,
                'sticky': True,
            },
        }
