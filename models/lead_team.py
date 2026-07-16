from odoo import models, fields, api
from odoo.exceptions import ValidationError


class LeadTeam(models.Model):
    _name = 'lead.team'
    _description = 'Lead Team'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='Team Name', required=True, tracking=True)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')

    # Multiple team leads per team
    team_lead_ids = fields.Many2many(
        'hr.employee',
        'lead_team_teamlead_rel',
        'team_id',
        'employee_id',
        string='Team Leads',
        tracking=True,
    )

    # Admission officers grouped under this team via member lines
    member_ids = fields.One2many(
        'lead.team.member',
        'team_id',
        string='Admission Officers',
    )

    member_count = fields.Integer(
        string='Officers', compute='_compute_member_count'
    )
    team_lead_count = fields.Integer(
        string='Team Leads', compute='_compute_team_lead_count'
    )

    @api.depends('member_ids')
    def _compute_member_count(self):
        for rec in self:
            rec.member_count = len(rec.member_ids)

    @api.depends('team_lead_ids')
    def _compute_team_lead_count(self):
        for rec in self:
            rec.team_lead_count = len(rec.team_lead_ids)

    @api.constrains('team_lead_ids', 'member_ids')
    def _check_no_overlap(self):
        """A person cannot be both a team lead and an admission officer in the same team."""
        for rec in self:
            tl_employees = rec.team_lead_ids
            member_employees = rec.member_ids.mapped('employee_id')
            overlap = tl_employees & member_employees
            if overlap:
                names = ', '.join(overlap.mapped('name'))
                raise ValidationError(
                    f"The following person(s) cannot be both Team Lead and Admission Officer "
                    f"in the same team: {names}"
                )


class LeadTeamMember(models.Model):
    _name = 'lead.team.member'
    _description = 'Lead Team Member (Admission Officer)'
    _rec_name = 'employee_id'
    _order = 'team_id, employee_id'

    team_id = fields.Many2one(
        'lead.team', string='Team', required=True, ondelete='cascade'
    )
    # Each member line is linked to a specific team lead within the team
    team_lead_id = fields.Many2one(
        'hr.employee',
        string='Reporting Team Lead',
        domain="[('id', 'in', parent.team_lead_ids)]",
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Admission Officer', required=True
    )
    user_id = fields.Many2one(
        'res.users', string='User', related='employee_id.user_id', store=True
    )

    _sql_constraints = [
        (
            'unique_member_per_team',
            'UNIQUE(team_id, employee_id)',
            'This admission officer is already a member of this team.',
        )
    ]
