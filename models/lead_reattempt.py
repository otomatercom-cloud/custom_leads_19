from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Model: otomater.lead.reattempt
# --------------------------------------------------------------------------
class OtomaterLeadReattempt(models.Model):
    _name = 'otomater.lead.reattempt'
    _description = 'Re-Attempt Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'request_date desc, id desc'

    # ── Identity ───────────────────────────────────────────────────────────
    name = fields.Char(
        string='Reference',
        default=lambda self: _('New'),
        copy=False,
        readonly=True,
        tracking=True,
    )

    lead_id = fields.Many2one(
        'leads.logic',
        string='Original Lead',
        required=True,
        ondelete='cascade',
        tracking=True,
    )

    # ── Ownership ──────────────────────────────────────────────────────────
    existing_owner_id = fields.Many2one(
        'hr.employee',
        string='Existing Owner',
        tracking=True,
    )
    requested_owner_id = fields.Many2one(
        'hr.employee',
        string='Requested By (Officer)',
        default=lambda self: self.env.user.employee_id.id,
        tracking=True,
    )

    # ── Dates ──────────────────────────────────────────────────────────────
    request_date = fields.Datetime(
        string='Request Date',
        default=fields.Datetime.now,
        readonly=True,
    )
    review_date = fields.Datetime(string='Review Date', readonly=True, tracking=True)
    assignment_date = fields.Datetime(string='Assignment Date', readonly=True, tracking=True)

    # ── Lead Details ───────────────────────────────────────────────────────
    old_source_id = fields.Many2one(
        'leads.sources',
        string='Old Source (Before Re-Attempt)',
        readonly=True,
        tracking=True,
        help="The lead's source at the time this re-attempt request was created.",
    )
    source_id = fields.Many2one(
        'leads.sources',
        string='New Source (Requested)',
        tracking=True,
        help="The new source to apply to the lead upon approval.",
    )
    course_id = fields.Many2many('course.interested', string='Course Interested')
    remarks = fields.Text(string='Remarks / Notes')

    duplicate_type = fields.Selection(
        [
            ('phone', 'Duplicate Phone'),
            ('email', 'Duplicate Email'),
            ('both', 'Duplicate Phone & Email'),
        ],
        string='Duplicate Type',
        tracking=True,
    )

    mobile = fields.Char(string='Mobile Number')
    email = fields.Char(string='Email Address')

    # ── Workflow Status ────────────────────────────────────────────────────
    review_status = fields.Selection(
        [
            ('pending_review', 'Pending Review'),
            ('approved', 'Approved'),
            ('assigned', 'Assigned'),
            ('rejected', 'Rejected'),
        ],
        string='Status',
        default='pending_review',
        required=True,
        tracking=True,
        copy=False,
    )

    # ── Assignment ─────────────────────────────────────────────────────────
    team_lead_id = fields.Many2one(
        'res.users',
        string='Reviewed By (Team Lead)',
        tracking=True,
    )
    admission_officer_id = fields.Many2one(
        'res.users',
        string='Assigned Admission Officer',
        tracking=True,
    )

    # ── Rejection ─────────────────────────────────────────────────────────
    rejection_reason = fields.Text(string='Rejection Reason', tracking=True)

    # ── Priority & Count ───────────────────────────────────────────────────
    priority = fields.Selection(
        [('0', 'Normal'), ('1', 'Low'), ('2', 'High'), ('3', 'Very High')],
        string='Priority',
        default='0',
    )

    re_attempt_count = fields.Integer(
        string='Re-Attempt #',
        default=1,
        readonly=True,
    )

    # ── Meta ───────────────────────────────────────────────────────────────
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    # ── Computed fields for views ──────────────────────────────────────────
    lead_quality = fields.Selection(
        related='lead_id.lead_quality',
        string='Lead Quality',
        readonly=True,
    )
    lead_owner_name = fields.Char(
        related='lead_id.lead_owner.name',
        string='Lead Owner',
        readonly=True,
    )

    # ── Constraints ────────────────────────────────────────────────────────
    @api.constrains('review_status', 'rejection_reason')
    def _check_rejection_reason(self):
        for rec in self:
            if rec.review_status == 'rejected' and not rec.rejection_reason:
                raise ValidationError(_('A rejection reason is mandatory when rejecting a re-attempt request.'))

    @api.constrains('review_status', 'admission_officer_id')
    def _check_assignment_officer(self):
        for rec in self:
            if rec.review_status == 'assigned' and not rec.admission_officer_id:
                raise ValidationError(_('Please select an Admission Officer before assigning the re-attempt.'))

    # ── Create ─────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('otomater.lead.reattempt') or _('New')
        records = super().create(vals_list)
        for rec in records:
            # Capture old source from the lead at request time
            if rec.lead_id and rec.lead_id.leads_source and not rec.old_source_id:
                rec.old_source_id = rec.lead_id.leads_source.id
            # Update lead flags
            rec.lead_id.sudo().write({
                'has_pending_reattempt': True,
                'last_re_attempt_date': fields.Datetime.now(),
            })
            # Post chatter on the original lead
            rec.lead_id.message_post(
                body=Markup(
                    "<div><strong>🔁 Re-Attempt Request Created</strong><br/>"
                    "<strong>Reference:</strong> {name}<br/>"
                    "<strong>Requested By:</strong> {officer}<br/>"
                    "<strong>Duplicate Type:</strong> {dtype}</div>"
                ).format(
                    name=rec.name,
                    officer=rec.requested_owner_id.name if rec.requested_owner_id else _('Unknown'),
                    dtype=dict(self._fields['duplicate_type'].selection).get(rec.duplicate_type, ''),
                ),
                subtype_xmlid='mail.mt_note',
            )
        return records

    # ────────────────────────────────────────────────────────────────────
    # Workflow Actions
    # ────────────────────────────────────────────────────────────────────

    def action_open_lead(self):
        """Navigate to the original lead record."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lead'),
            'res_model': 'leads.logic',
            'view_mode': 'form',
            'res_id': self.lead_id.id,
            'target': 'current',
        }

    def action_approve(self):
        """Team Lead approves the re-attempt.
        If a new source is set, the lead's source is updated from old to new.
        """
        for rec in self:
            if rec.review_status != 'pending_review':
                raise UserError(_('Only Pending Review requests can be approved.'))
            rec.write({
                'review_status': 'approved',
                'team_lead_id': self.env.user.id,
                'review_date': fields.Datetime.now(),
            })
            # Increment re_attempt_count on lead
            lead = rec.lead_id
            new_count = (lead.re_attempt_count or 0) + 1

            # ── Source change on approval ──────────────────────────────
            old_source_name = rec.old_source_id.name if rec.old_source_id else _('(None)')
            new_source_name = rec.source_id.name if rec.source_id else None

            lead_write_vals = {
                're_attempt_count': new_count,
                'last_re_attempt_date': fields.Datetime.now(),
                'has_pending_reattempt': False,
            }
            if rec.source_id:
                lead_write_vals['leads_source'] = rec.source_id.id

            lead.sudo().write(lead_write_vals)

            # ── Chatter on lead ────────────────────────────────────────
            source_line = Markup(
                "<strong>Source Change:</strong> {old} → <strong>{new}</strong><br/>"
            ).format(
                old=old_source_name,
                new=new_source_name or _('(unchanged)'),
            ) if new_source_name else Markup(
                "<strong>Source:</strong> {old} (no change requested)<br/>"
            ).format(old=old_source_name)

            lead.message_post(
                body=Markup(
                    "<div><strong>✅ Re-Attempt Approved</strong><br/>"
                    "<strong>Reference:</strong> {name}<br/>"
                    "<strong>Approved By:</strong> {tl}<br/>"
                    "{source_line}"
                    "<strong>Total Re-Attempts:</strong> {cnt}</div>"
                ).format(
                    name=rec.name,
                    tl=self.env.user.name,
                    source_line=source_line,
                    cnt=new_count,
                ),
            )
            # ── Chatter on re-attempt record ───────────────────────────
            if new_source_name:
                rec.message_post(
                    body=_('✅ Approved by %s. Lead source changed: %s → %s') % (
                        self.env.user.name, old_source_name, new_source_name
                    )
                )
            else:
                rec.message_post(
                    body=_('✅ Request approved by %s. No source change requested.') % self.env.user.name
                )

    def action_assign_officer(self):
        """Team Lead assigns an Admission Officer."""
        for rec in self:
            if rec.review_status not in ('pending_review', 'approved'):
                raise UserError(_('Only Pending or Approved requests can be assigned.'))
            if not rec.admission_officer_id:
                raise UserError(_('Please select an Admission Officer before assigning.'))
            rec.write({
                'review_status': 'assigned',
                'team_lead_id': self.env.user.id,
                'review_date': rec.review_date or fields.Datetime.now(),
                'assignment_date': fields.Datetime.now(),
            })
            # Create mail.activity for the officer
            if rec.admission_officer_id:
                self.env['mail.activity'].create({
                    'res_model': 'otomater.lead.reattempt',
                    'res_id': rec.id,
                    'user_id': rec.admission_officer_id.id,
                    'summary': _('Re-Attempt Assigned to You'),
                    'note': _(
                        'Re-Attempt request %s has been assigned to you for lead %s.'
                    ) % (rec.name, rec.lead_id.name),
                    'date_deadline': fields.Date.today(),
                    'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                })
                # Inbox notification
                if rec.admission_officer_id.partner_id:
                    self.env['mail.message'].create({
                        'message_type': 'notification',
                        'body': _(
                            "Re-Attempt request <strong>%s</strong> for lead <strong>%s</strong> has been assigned to you."
                        ) % (rec.name, rec.lead_id.name),
                        'subject': _('Re-Attempt Assigned'),
                        'model': 'otomater.lead.reattempt',
                        'res_id': rec.id,
                        'partner_ids': [(4, rec.admission_officer_id.partner_id.id)],
                        'author_id': self.env.user.partner_id.id,
                        'notification_ids': [(0, 0, {
                            'res_partner_id': rec.admission_officer_id.partner_id.id,
                            'notification_type': 'inbox',
                        })],
                    })
            rec.lead_id.sudo().write({'has_pending_reattempt': False})
            rec.message_post(
                body=_('📋 Assigned to %s by %s.') % (
                    rec.admission_officer_id.name, self.env.user.name
                )
            )

    def action_reject(self):
        """Open rejection wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Re-Attempt'),
            'res_model': 'reattempt.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_reattempt_id': self.id},
        }

    def action_reject_direct(self, reason):
        """Called from reject wizard."""
        for rec in self:
            if not reason:
                raise ValidationError(_('Rejection reason is mandatory.'))
            rec.write({
                'review_status': 'rejected',
                'rejection_reason': reason,
                'team_lead_id': self.env.user.id,
                'review_date': fields.Datetime.now(),
            })
            rec.lead_id.sudo().write({'has_pending_reattempt': False})
            rec.lead_id.message_post(
                body=Markup(
                    "<div><strong>❌ Re-Attempt Rejected</strong><br/>"
                    "<strong>Reference:</strong> {name}<br/>"
                    "<strong>Rejected By:</strong> {tl}<br/>"
                    "<strong>Reason:</strong> {reason}</div>"
                ).format(name=rec.name, tl=self.env.user.name, reason=reason),
            )
            rec.message_post(body=_('❌ Rejected by %s. Reason: %s') % (self.env.user.name, reason))

    def action_reset_to_draft(self):
        """Reset to Pending Review."""
        for rec in self:
            rec.write({
                'review_status': 'pending_review',
                'team_lead_id': False,
                'admission_officer_id': False,
                'review_date': False,
                'assignment_date': False,
                'rejection_reason': False,
            })
            rec.lead_id.sudo().write({'has_pending_reattempt': True})
            rec.message_post(body=_('🔄 Reset to Pending Review by %s.') % self.env.user.name)

    def action_add_note(self):
        """Open chatter compose for officer notes."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': 'otomater.lead.reattempt',
                'default_res_ids': [self.id],
                'default_composition_mode': 'comment',
            },
        }

    def action_schedule_followup(self):
        """Schedule a follow-up activity."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Schedule Follow-Up'),
            'res_model': 'mail.activity',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': 'otomater.lead.reattempt',
                'default_res_id': self.id,
            },
        }

    def action_mark_completed(self):
        """Officer marks the re-attempt as completed (archived)."""
        for rec in self:
            rec.write({'active': False})
            rec.message_post(body=_('✅ Marked as completed by %s.') % self.env.user.name)


# --------------------------------------------------------------------------
# Rejection Wizard
# --------------------------------------------------------------------------
class ReattemptRejectWizard(models.TransientModel):
    _name = 'reattempt.reject.wizard'
    _description = 'Re-Attempt Rejection Wizard'

    reattempt_id = fields.Many2one('otomater.lead.reattempt', required=True)
    rejection_reason = fields.Text(string='Rejection Reason', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        self.reattempt_id.action_reject_direct(self.rejection_reason)
        return {'type': 'ir.actions.act_window_close'}
