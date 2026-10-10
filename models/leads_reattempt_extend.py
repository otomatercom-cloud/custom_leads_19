from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class LeadsLogicReattemptExtension(models.Model):
    """Extends leads.logic with re-attempt tracking fields."""
    _inherit = 'leads.logic'

    # ── Re-Attempt Extension Fields ────────────────────────────────────────
    re_attempt_count = fields.Integer(
        string='Re-Attempt Count',
        default=0,
        readonly=True,
        copy=False,
    )
    last_re_attempt_date = fields.Datetime(
        string='Last Re-Attempt Date',
        readonly=True,
        copy=False,
    )
    reattempt_ids = fields.One2many(
        'otomater.lead.reattempt',
        'lead_id',
        string='Re-Attempts',
        copy=False,
    )
    has_pending_reattempt = fields.Boolean(
        string='Has Pending Re-Attempt',
        default=False,
        copy=False,
    )
    reattempt_count_display = fields.Integer(
        string='Re-Attempts',
        compute='_compute_reattempt_count_display',
    )

    @api.depends('reattempt_ids')
    def _compute_reattempt_count_display(self):
        for rec in self:
            rec.reattempt_count_display = len(rec.reattempt_ids)

    # ── Smart Button Action ────────────────────────────────────────────────
    def action_view_reattempts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Re-Attempts'),
            'res_model': 'otomater.lead.reattempt',
            'view_mode': 'list,form,kanban',
            'domain': [('lead_id', '=', self.id)],
            'context': {
                'default_lead_id': self.id,
                'default_mobile': self.phone_number,
                'default_email': self.email_address,
                'default_existing_owner_id': self.lead_owner.id if self.lead_owner else False,
                'default_source_id': self.leads_source.id if self.leads_source else False,
            },
        }

    # ── Override create to intercept duplicates ───────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        """
        Before creating a lead, check for duplicate phone/email.
        If duplicate found:
          - Block creation
          - Create otomater.lead.reattempt record
          - Raise warning to user
        """
        if self.env.context.get('otm_odoo17_import'):
            # Odoo 17 import does its own duplicate check
            return super(LeadsLogicReattemptExtension, self).create(vals_list)

        processed_results = []
        reattempts_to_create = []

        for vals in vals_list:
            phone = vals.get('phone_number', '').replace(' ', '')
            email = vals.get('email_address', '')

            existing_lead = None
            duplicate_type = False

            if phone:
                last_10 = phone[-10:] if len(phone) >= 10 else phone
                existing_lead = self.sudo().search([
                    ('phone_number', 'like', '%' + last_10),
                ], limit=1)
                if existing_lead:
                    duplicate_type = 'phone'

            if not existing_lead and email:
                existing_lead = self.sudo().search([
                    ('email_address', '=ilike', email),
                ], limit=1)
                if existing_lead:
                    duplicate_type = 'email'

            if not existing_lead and phone and email:
                pass  # already checked both individually
            elif existing_lead and phone and email:
                # Check if both match
                last_10 = phone[-10:] if len(phone) >= 10 else phone
                phone_match = self.sudo().search([
                    ('phone_number', 'like', '%' + last_10),
                ], limit=1)
                email_match = self.sudo().search([
                    ('email_address', '=ilike', email),
                ], limit=1)
                if phone_match and email_match and phone_match.id == email_match.id:
                    duplicate_type = 'both'

            if existing_lead:
                reattempts_to_create.append({
                    'lead': existing_lead,
                    'vals': vals,
                    'duplicate_type': duplicate_type,
                })
            else:
                processed_results.append(vals)

        # Create re-attempt records for duplicates
        for item in reattempts_to_create:
            existing = item['lead']
            vals = item['vals']
            dtype = item['duplicate_type']

            # Determine requesting officer
            requested_owner = False
            if self.env.user.employee_id:
                requested_owner = self.env.user.employee_id.id

            reattempt_vals = {
                'lead_id': existing.id,
                'existing_owner_id': existing.lead_owner.id if existing.lead_owner else False,
                'requested_owner_id': requested_owner,
                'request_date': fields.Datetime.now(),
                'source_id': vals.get('leads_source', False),
                'remarks': vals.get('remarks', False),
                'duplicate_type': dtype,
                'mobile': vals.get('phone_number', ''),
                'email': vals.get('email_address', ''),
                'review_status': 'pending_review',
                're_attempt_count': (existing.re_attempt_count or 0) + 1,
            }
            # One open request per officer + lead: a second try with the same number does not
            # pile up more requests, the officer is just told again who owns the lead.
            Reattempt = self.env['otomater.lead.reattempt'].sudo()
            already_open = Reattempt.search([
                ('lead_id', '=', existing.id),
                ('requested_owner_id', '=', requested_owner),
                ('review_status', '=', 'pending_review'),
            ], limit=1) if requested_owner else Reattempt
            if already_open:
                request_note = _("You already have a Re-Attempt Request pending for this lead. "
                                 "Please wait for Team Lead approval.")
            else:
                # Separate transaction so the request is kept although this one is rolled back.
                with self.env.registry.cursor() as new_cr:
                    new_env = api.Environment(new_cr, self.env.uid, self.env.context)
                    new_env['otomater.lead.reattempt'].sudo().create(reattempt_vals)
                request_note = _("A Re-Attempt Request has been created and sent to the Team Lead "
                                 "for review. Please wait for approval.")

            owner = existing.lead_owner
            assigned_on = existing.assigned_date or existing.date_of_adding
            quality = dict(existing._fields['lead_quality'].selection).get(existing.lead_quality, '') \
                if existing.lead_quality else ''
            raise ValidationError(_(
                "Duplicate lead - not allowed.\n\n"
                "This %(kind)s already exists in the system.\n\n"
                "Lead: %(name)s\n"
                "Reference: %(ref)s\n"
                "Assigned to: %(owner)s\n"
                "Team: %(team)s\n"
                "Assigned / added on: %(date)s\n"
                "Lead quality: %(quality)s\n\n"
                "%(note)s"
            ) % {
                'kind': dict(self.env['otomater.lead.reattempt']._fields['duplicate_type'].selection).get(dtype, dtype),
                'name': existing.name or '',
                'ref': existing.reference_no or '',
                'owner': owner.name if owner else _('Not assigned'),
                'team': existing.team_id.name if existing.team_id else '-',
                'date': assigned_on or '-',
                'quality': quality or '-',
                'note': request_note,
            })

        if not processed_results:
            # All were duplicates — nothing to create
            return self.browse([])

        return super(LeadsLogicReattemptExtension, self).create(processed_results)
