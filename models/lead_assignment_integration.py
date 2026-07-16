"""
Extends:
  - lead.assignment.history  – adds rule/type/team/audit columns
  - leads.logic              – hooks create() for auto-assignment;
                               extends write() for manual reassignment audit
"""

from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extend lead.assignment.history
# ---------------------------------------------------------------------------
class LeadAssignmentHistoryExtended(models.Model):
    _inherit = 'lead.assignment.history'

    assigned_team_id = fields.Many2one(
        'lead.team',
        string='Assigned Team',
        ondelete='set null',
        index=True,
    )
    assignment_rule_id = fields.Many2one(
        'lead.assignment.rule',
        string='Assignment Rule',
        ondelete='set null',
    )
    assignment_type = fields.Selection([
        ('all_teams',      'All Teams (Round Robin)'),
        ('selected_teams', 'Selected Teams (Bucket)'),
        ('source_based',   'Source Based'),
        ('manual',         'Manual Reassignment'),
    ], string='Assignment Type')

    # Reassignment audit columns
    old_team_id  = fields.Many2one('lead.team',    string='Previous Team',  ondelete='set null')
    old_owner_id = fields.Many2one('hr.employee',  string='Previous Owner', ondelete='set null')
    new_team_id  = fields.Many2one('lead.team',    string='New Team',       ondelete='set null')
    new_owner_id = fields.Many2one('hr.employee',  string='New Owner',      ondelete='set null')
    changed_by   = fields.Many2one('res.users',    string='Changed By',
                                   default=lambda self: self.env.user)


# ---------------------------------------------------------------------------
# Extend leads.logic
# ---------------------------------------------------------------------------
class LeadsLogicAssignment(models.Model):
    _inherit = 'leads.logic'

    assignment_history_count = fields.Integer(
        string='Assignments',
        compute='_compute_assignment_history_count',
    )

    def _compute_assignment_history_count(self):
        for rec in self:
            rec.assignment_history_count = len(rec.assignment_history_ids)

    # ── Smart-button action ─────────────────────────────────────────────────
    def action_view_assignment_history(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assignment History'),
            'res_model': 'lead.assignment.history',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id},
        }

    # ── create() – trigger auto-assignment after super ──────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # leads.py defines lead_owner with
            #   default=lambda self: self.env.user.employee_id.id
            # That default only kicks in when 'lead_owner' is ABSENT from
            # vals. The backend form always submits it explicitly (the
            # widget renders the default, then sends it back), so manual
            # creation is unaffected. But external/API creates that omit
            # the key — e.g. the Google Sheet sync, which has no "owner"
            # column to map — would otherwise silently inherit the
            # *syncing user's* employee record as owner, bypassing
            # auto-assignment entirely. Force it to False here so those
            # leads always go through the assignment rule below.
            if 'lead_owner' not in vals:
                vals['lead_owner'] = False
        records = super().create(vals_list)
        for lead in records:
            # Only auto-assign if no lead_owner was explicitly supplied
            if not lead.lead_owner:
                try:
                    # Isolate each lead's assignment in its own savepoint —
                    # if it fails partway through, only this lead rolls
                    # back; the rest of the batch (other leads created in
                    # the same create_multi call, e.g. during a bulk
                    # Google Sheet sync) stays unaffected.
                    with self.env.cr.savepoint():
                        self._auto_assign_lead(lead)
                        self.env.flush_all()
                except Exception as e:
                    _logger.error(
                        'LeadAssignment ERROR for lead %s: %s', lead.id, str(e)
                    )
        return records

    def _auto_assign_lead(self, lead):
        """Find the first active rule and run assignment."""
        rule = self.env['lead.assignment.rule'].search(
            [('active', '=', True)],
            order='sequence, id',
            limit=1,
        )
        if not rule:
            return

        team, employee = rule.assign_lead(lead)
        if not employee and not team:
            return

        # Capture old state
        old_team  = lead.team_id  if hasattr(lead, 'team_id')  else False
        old_owner = lead.lead_owner

        # Write owner — suppress base write() history via context flag
        if employee:
            lead.with_context(skip_assignment_history=True).write({
                'lead_owner':      employee.id,
                'assigned_date':   fields.Date.today(),
                'reassign_date':   fields.Datetime.now(),
            })

        # Re-fetch resolved team (computed from lead_owner)
        lead.invalidate_recordset(['team_id'])
        resolved_team = lead.team_id if hasattr(lead, 'team_id') else team

        # Create rich history record
        self.env['lead.assignment.history'].sudo().create({
            'lead_id':            lead.id,
            'owner_id':           employee.id if employee else False,
            'assigned_team_id':   (resolved_team.id if resolved_team else False) or (team.id if team else False),
            'assignment_rule_id': rule.id,
            'assignment_type':    rule.assignment_type,
            'old_team_id':        old_team.id  if old_team  else False,
            'old_owner_id':       old_owner.id if old_owner else False,
            'new_team_id':        (resolved_team.id if resolved_team else False) or (team.id if team else False),
            'new_owner_id':       employee.id if employee else False,
            'changed_by':         self.env.uid,
            'assigned_date':      fields.Datetime.now(),
            'assigned_by':        self.env.uid,
        })

    # ── write() – manual reassignment audit ────────────────────────────────
    def write(self, vals):
        """
        When lead_owner changes manually (not via engine), create a rich
        audit history record that includes old/new team and owner.
        The base leads.py write() is already guarded with
        `skip_assignment_history` context — so when we set that context here
        we own the history record exclusively.
        """
        if 'lead_owner' in vals and not self.env.context.get('skip_assignment_history'):
            # Snapshot old values per record before writing
            snapshots = {}
            for record in self:
                if vals['lead_owner'] != record.lead_owner.id:
                    snapshots[record.id] = {
                        'old_owner': record.lead_owner,
                        'old_team':  record.team_id if hasattr(record, 'team_id') else False,
                    }

            # Delegate to super with skip flag to suppress base write() history
            result = super(LeadsLogicAssignment, self.with_context(
                skip_assignment_history=True
            )).write(vals)

            # Now create our rich history records
            for record in self:
                snap = snapshots.get(record.id)
                if not snap:
                    continue
                record.invalidate_recordset(['team_id'])
                new_team  = record.team_id if hasattr(record, 'team_id') else False
                new_owner = self.env['hr.employee'].browse(vals['lead_owner'])

                self.env['lead.assignment.history'].sudo().create({
                    'lead_id':            record.id,
                    'owner_id':           vals['lead_owner'],
                    'assigned_team_id':   new_team.id  if new_team  else False,
                    'assignment_rule_id': False,
                    'assignment_type':    'manual',
                    'old_team_id':        snap['old_team'].id  if snap['old_team']  else False,
                    'old_owner_id':       snap['old_owner'].id if snap['old_owner'] else False,
                    'new_team_id':        new_team.id  if new_team  else False,
                    'new_owner_id':       vals['lead_owner'],
                    'changed_by':         self.env.uid,
                    'assigned_date':      fields.Datetime.now(),
                    'assigned_by':        self.env.uid,
                })
            return result

        return super().write(vals)
