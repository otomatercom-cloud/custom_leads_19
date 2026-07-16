"""
Lead Assignment Engine for custom_leads_19
==========================================
Implements:
  - lead.assignment.rule          – configurable rule (all_teams / selected_teams / source_based)
  - lead.assignment.source.rule   – per-source → team(s) mapping
  - lead.assignment.counter       – DB-safe round-robin counters (teams + members)
  - Assignment logic entry-point  : LeadAssignmentEngine.assign(lead)

All DB mutations that must survive concurrent requests use
SELECT … FOR UPDATE SKIP LOCKED (PostgreSQL) to prevent double-assignment.
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Round-Robin Counter  (one row per team, one row per member per team)
# ---------------------------------------------------------------------------
class LeadAssignmentCounter(models.Model):
    _name = 'lead.assignment.counter'
    _description = 'Lead Assignment Round-Robin Counter'

    # For team-level round-robin
    team_id = fields.Many2one('lead.team', string='Team', ondelete='cascade', index=True)
    # For member-level round-robin
    member_id = fields.Many2one('lead.team.member', string='Member', ondelete='cascade', index=True)
    counter = fields.Integer(string='Counter', default=0)

    _sql_constraints = [
        ('unique_team_counter', 'UNIQUE(team_id)',
         'Duplicate team counter – only one row per team allowed.'),
        ('unique_member_counter', 'UNIQUE(member_id)',
         'Duplicate member counter – only one row per member allowed.'),
    ]


# ---------------------------------------------------------------------------
# Assignment Rule
# ---------------------------------------------------------------------------
class LeadAssignmentRule(models.Model):
    _name = 'lead.assignment.rule'
    _description = 'Lead Assignment Rule'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'sequence, id'

    name = fields.Char(string='Rule Name', required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)

    assignment_type = fields.Selection([
        ('all_teams', 'Auto – All Active Teams (Round Robin)'),
        ('selected_teams', 'Selected Teams (Bucket)'),
        ('source_based', 'Source Based'),
    ], string='Assignment Type', required=True, default='all_teams', tracking=True)

    # ── Selected-teams config ───────────────────────────────────────────────
    team_ids = fields.Many2many(
        'lead.team',
        'lead_assignment_rule_team_rel',
        'rule_id', 'team_id',
        string='Selected Teams',
    )
    bucket_size = fields.Integer(
        string='Bucket Size',
        default=10,
        help='Number of leads per team before cycling to the next.',
    )

    # ── Member assignment config ────────────────────────────────────────────
    include_team_leads = fields.Boolean(
        string='Include Team Leads',
        default=False,
        tracking=True,
        help='If enabled, team leads also participate in lead assignment alongside members.',
    )

    # ── Source rule lines (inline list) ────────────────────────────────────
    source_rule_ids = fields.One2many(
        'lead.assignment.source.rule',
        'rule_id',
        string='Source Rules',
    )

    # ── Counters ────────────────────────────────────────────────────────────
    # Global lead counter used for bucket calculation (selected_teams)
    global_lead_counter = fields.Integer(
        string='Global Lead Counter',
        default=0,
        copy=False,
        help='Auto-incremented counter used for bucket-based assignment.',
    )

    def _get_active_teams_ordered(self):
        """Return active lead.team records ordered by name for round-robin."""
        return self.env['lead.team'].search([('active', '=', True)], order='name')

    def _get_assignable_users(self, team):
        """
        Return res.users records that should receive leads for a given team.
        Respects include_team_leads flag.
        """
        users = self.env['res.users']

        # Member users
        member_users = team.member_ids.mapped('user_id').filtered(lambda u: u.active)
        users |= member_users

        if self.include_team_leads:
            tl_users = team.team_lead_ids.mapped('user_id').filtered(lambda u: u and u.active)
            users |= tl_users

        return users

    def _get_assignable_employees(self, team):
        """
        Return hr.employee records that should receive leads for a given team.
        """
        employees = self.env['hr.employee']

        member_employees = team.member_ids.mapped('employee_id').filtered(
            lambda e: e.user_id and e.user_id.active
        )
        employees |= member_employees

        if self.include_team_leads:
            tl_employees = team.team_lead_ids.filtered(
                lambda e: e.user_id and e.user_id.active
            )
            employees |= tl_employees

        return employees

    # ── Public entry point ──────────────────────────────────────────────────
    def assign_lead(self, lead):
        """
        Dispatch to the correct assignment strategy based on assignment_type.
        Returns (team, employee) or (False, False) if nothing could be assigned.
        """
        self.ensure_one()
        if self.assignment_type == 'all_teams':
            return self._assign_all_teams(lead)
        elif self.assignment_type == 'selected_teams':
            return self._assign_selected_teams(lead)
        elif self.assignment_type == 'source_based':
            return self._assign_source_based(lead)
        return False, False

    # ── Button: Assign Now ──────────────────────────────────────────────────
    def action_assign_now(self):
        """
        Triggered from the 'Assign Now' button on the rule form.
        Immediately runs this rule against every currently unassigned lead
        (lead_owner = False) and writes the resulting owner/team, exactly
        the way the automatic create()-time assignment does — including
        the rich lead.assignment.history audit trail.
        """
        self.ensure_one()

        unassigned_leads = self.env['leads.logic'].search([
            ('lead_owner', '=', False),
            ('state', '!=', 'lost'),
        ], order='create_date asc')

        if not unassigned_leads:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Nothing to Assign'),
                    'message': _('There are no unassigned leads right now.'),
                    'type': 'info',
                    'sticky': False,
                },
            }

        assigned_count = 0
        skipped_count = 0

        for lead in unassigned_leads:
            try:
                # Everything for this lead — the round-robin pick (raw SQL),
                # the write, and the history record — happens inside one
                # savepoint. If anything fails, only this lead's changes
                # get rolled back; the rest of the batch (and the eventual
                # end-of-request flush) stays healthy instead of failing
                # with an opaque "transaction is aborted" error.
                with self.env.cr.savepoint():
                    team, employee = self.assign_lead(lead)
                    if not employee:
                        skipped_count += 1
                        continue

                    old_team = lead.team_id if hasattr(lead, 'team_id') else False
                    old_owner = lead.lead_owner

                    lead.with_context(skip_assignment_history=True).write({
                        'lead_owner': employee.id,
                        'assigned_date': fields.Date.today(),
                        'reassign_date': fields.Datetime.now(),
                    })

                    lead.invalidate_recordset(['team_id'])
                    resolved_team = lead.team_id if hasattr(lead, 'team_id') else team
                    final_team_id = (resolved_team.id if resolved_team else False) or (team.id if team else False)

                    self.env['lead.assignment.history'].sudo().create({
                        'lead_id': lead.id,
                        'owner_id': employee.id,
                        'assigned_team_id': final_team_id,
                        'assignment_rule_id': self.id,
                        'assignment_type': self.assignment_type,
                        'old_team_id': old_team.id if old_team else False,
                        'old_owner_id': old_owner.id if old_owner else False,
                        'new_team_id': final_team_id,
                        'new_owner_id': employee.id,
                        'changed_by': self.env.uid,
                        'assigned_date': fields.Datetime.now(),
                        'assigned_by': self.env.uid,
                    })

                    # Flush now, inside the savepoint, so any DB-level error
                    # surfaces and is isolated here rather than at the final
                    # end-of-request flush where the real cause is hidden.
                    self.env.flush_all()

                assigned_count += 1
            except Exception as e:
                _logger.error(
                    'LeadAssignment [Assign Now]: error assigning lead %s with rule "%s": %s',
                    lead.id, self.name, str(e)
                )
                skipped_count += 1

        if assigned_count:
            message = _('%(count)s lead(s) assigned successfully.', count=assigned_count)
            if skipped_count:
                message += ' ' + _(
                    '%(skipped)s lead(s) were skipped (no eligible team/member found).',
                    skipped=skipped_count,
                )
            msg_type = 'success'
        else:
            message = _(
                'No leads could be assigned. Make sure the configured teams '
                'have active members.'
            )
            msg_type = 'warning'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Immediate Assignment Complete'),
                'message': message,
                'type': msg_type,
                'sticky': True,
            },
        }

    # ── Strategy: all_teams ─────────────────────────────────────────────────
    def _assign_all_teams(self, lead):
        teams = self._get_active_teams_ordered()
        if not teams:
            _logger.warning('LeadAssignment [all_teams]: no active teams found.')
            return False, False

        team = self._round_robin_team(teams)
        if not team:
            return False, False

        employee = self._round_robin_member(team)
        return team, employee

    # ── Strategy: selected_teams ────────────────────────────────────────────
    def _assign_selected_teams(self, lead):
        teams = self.team_ids.filtered('active')
        if not teams:
            _logger.warning('LeadAssignment [selected_teams]: no active selected teams.')
            return False, False

        # Increment global counter safely
        team = self._bucket_team(teams)
        if not team:
            return False, False

        employee = self._round_robin_member(team)
        return team, employee

    # ── Strategy: source_based ──────────────────────────────────────────────
    def _assign_source_based(self, lead):
        source = lead.leads_source
        if not source:
            _logger.warning('LeadAssignment [source_based]: lead has no source.')
            return False, False

        source_rule = self.source_rule_ids.filtered(
            lambda r: r.active and r.source_id.id == source.id
        )
        if not source_rule:
            _logger.warning(
                'LeadAssignment [source_based]: no rule for source "%s".', source.name
            )
            return False, False

        # Use the first matching active rule
        source_rule = source_rule[0]
        teams = source_rule.team_ids.filtered('active')
        if not teams:
            return False, False

        # Use per-source counter for multi-team round-robin (requirement 5)
        team = source_rule._next_team()
        if not team:
            return False, False

        employee = self._round_robin_member(team)
        return team, employee

    # ── Round-Robin helpers ─────────────────────────────────────────────────
    def _round_robin_team(self, teams):
        """
        Select the next team using a round-robin counter stored in
        lead.assignment.counter.  Uses SELECT FOR UPDATE to prevent races.
        """
        if not teams:
            return False

        team_list = list(teams)

        # We use a single "rule-level" row keyed by the rule + a synthetic
        # member=False + team=False combo isn't valid, so we use a dedicated
        # approach: one counter row PER RULE stored as team_id=False, member_id=False
        # is ambiguous with SQL UNIQUE.  Instead we embed the counter in the
        # rule record itself and lock via SELECT FOR UPDATE on the rule row.

        self.env.cr.execute(
            'SELECT global_lead_counter FROM lead_assignment_rule '
            'WHERE id = %s FOR UPDATE',
            (self.id,)
        )
        row = self.env.cr.fetchone()
        current = row[0] if row else 0
        idx = current % len(team_list)
        next_counter = current + 1

        self.env.cr.execute(
            'UPDATE lead_assignment_rule SET global_lead_counter = %s WHERE id = %s',
            (next_counter, self.id)
        )

        return team_list[idx]

    def _bucket_team(self, teams):
        """
        Select team based on bucket logic.
        Bucket size leads go to Team[0], next bucket to Team[1], etc.
        Uses FOR UPDATE lock on the rule row.
        """
        if not teams:
            return False

        team_list = list(teams)
        bucket = max(self.bucket_size, 1)

        self.env.cr.execute(
            'SELECT global_lead_counter FROM lead_assignment_rule '
            'WHERE id = %s FOR UPDATE',
            (self.id,)
        )
        row = self.env.cr.fetchone()
        current = row[0] if row else 0

        # Which bucket are we in?
        team_idx = (current // bucket) % len(team_list)
        next_counter = current + 1

        self.env.cr.execute(
            'UPDATE lead_assignment_rule SET global_lead_counter = %s WHERE id = %s',
            (next_counter, self.id)
        )

        return team_list[team_idx]

    def _round_robin_member(self, team):
        """
        Select next assignable employee in the team using a per-team counter.
        Returns hr.employee or False.
        """
        employees = list(self._get_assignable_employees(team))
        if not employees:
            _logger.warning(
                'LeadAssignment: team "%s" has no assignable employees.', team.name
            )
            return False

        # Lock / fetch the team counter
        self.env.cr.execute(
            'SELECT id, counter FROM lead_assignment_counter '
            'WHERE team_id = %s AND member_id IS NULL FOR UPDATE',
            (team.id,)
        )
        row = self.env.cr.fetchone()

        if row:
            counter_id, current = row
            idx = current % len(employees)
            next_counter = current + 1
            self.env.cr.execute(
                'UPDATE lead_assignment_counter SET counter = %s WHERE id = %s',
                (next_counter, counter_id)
            )
        else:
            # Create the counter row
            counter = self.env['lead.assignment.counter'].sudo().create({
                'team_id': team.id,
                'counter': 1,
            })
            idx = 0

        return employees[idx]


# ---------------------------------------------------------------------------
# Source Assignment Rule
# ---------------------------------------------------------------------------
class LeadAssignmentSourceRule(models.Model):
    _name = 'lead.assignment.source.rule'
    _description = 'Lead Assignment Source Rule'
    _rec_name = 'source_id'
    _order = 'source_id'

    rule_id = fields.Many2one(
        'lead.assignment.rule',
        string='Assignment Rule',
        ondelete='cascade',
        required=True,
    )
    source_id = fields.Many2one(
        'leads.sources',
        string='Lead Source',
        required=True,
        ondelete='cascade',
    )
    team_ids = fields.Many2many(
        'lead.team',
        'lead_source_rule_team_rel',
        'source_rule_id', 'team_id',
        string='Teams',
        required=True,
    )
    active = fields.Boolean(default=True)

    # Per-source round-robin counter for multi-team sources
    source_counter = fields.Integer(default=0, copy=False)

    def _next_team(self):
        """Thread-safe team picker for multi-team sources."""
        teams = list(self.team_ids.filtered('active'))
        if not teams:
            return False

        self.env.cr.execute(
            'SELECT source_counter FROM lead_assignment_source_rule '
            'WHERE id = %s FOR UPDATE',
            (self.id,)
        )
        row = self.env.cr.fetchone()
        current = row[0] if row else 0
        idx = current % len(teams)
        self.env.cr.execute(
            'UPDATE lead_assignment_source_rule SET source_counter = %s WHERE id = %s',
            (current + 1, self.id)
        )
        return teams[idx]

    _sql_constraints = [
        ('unique_source_per_rule', 'UNIQUE(rule_id, source_id)',
         'A source can only appear once per assignment rule.'),
    ]
