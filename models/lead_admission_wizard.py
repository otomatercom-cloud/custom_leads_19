from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


DISTRICT_MAP = {
    'alappuzha': 'Alappuzha',
    'ernakulam': 'Ernakulam',
    'idukki': 'Idukki',
    'kannur': 'Kannur',
    'kasaragod': 'Kasaragod',
    'kollam': 'Kollam',
    'kottayam': 'Kottayam',
    'kozhikode': 'Kozhikode',
    'malappuram': 'Malappuram',
    'palakkad': 'Palakkad',
    'pathanamthitta': 'Pathanamthitta',
    'thiruvananthapuram': 'Thiruvananthapuram',
    'thrissur': 'Thrissur',
    'wayanad': 'Wayanad',
}

BRANCH_MAP = {
    'kochi': 'kochi',
    'ernakulam': 'kochi',
    'calicut': 'calicut',
    'kozhikode': 'kozhikode',
    'kottayam': 'kottayam',
    'trivandrum': 'trivandrum',
    'thiruvananthapuram': 'trivandrum',
    'malappuram': 'malappuram',
    'online': 'online',
}


class LeadAdmissionWizard(models.TransientModel):
    _name = 'lead.admission.wizard'
    _description = 'Lead Admission Wizard'

    lead_id = fields.Many2one('leads.logic', required=True, readonly=True)
    lead_name = fields.Char(related='lead_id.name', readonly=True)
    lead_phone = fields.Char(related='lead_id.phone_number', readonly=True)
    lead_email = fields.Char(related='lead_id.email_address', readonly=True)

    batch_required = fields.Boolean(
        string='Batch Required',
        compute='_compute_batch_required',
        default=False,
    )

    @api.depends()
    def _compute_batch_required(self):
        val = self.env['ir.config_parameter'].sudo().get_param(
            'custom_leads_19.admission_batch_required'
        )
        is_required = (val == '1')
        for rec in self:
            rec.batch_required = is_required

    batch_id = fields.Many2one(
        'student.batch', required=False,
        domain=[('active', '=', True)], string='Select Batch',
    )
    fee_structure_id = fields.Many2one(
        'fee.structure', string='Select Fee Structure',
        domain="[('batch_ids', 'in', batch_id), ('fee_type', '!=', 'admission')]",
    )

    fee_type_display = fields.Char(string='Fee Type', readonly=True)
    gst_rate_display = fields.Char(string='GST Rate', readonly=True)
    total_fee_display = fields.Float(string='Total Fee ₹', readonly=True, digits=(10, 2))
    base_fee_display = fields.Float(string='Base (Excl. GST) ₹', readonly=True, digits=(10, 2))
    gst_display = fields.Float(string='GST ₹', readonly=True, digits=(10, 2))
    admission_fee_display = fields.Float(string='Admission Fee ₹', readonly=True, digits=(10, 2))
    grand_total_display = fields.Float(string='Grand Total ₹', readonly=True, digits=(10, 2))
    installment_summary = fields.Text(string='Installment Schedule', readonly=True)
    available_fee_ids = fields.Many2many('fee.structure', compute='_compute_available_fees')

    @api.depends('batch_id')
    def _compute_available_fees(self):
        for rec in self:
            rec.available_fee_ids = rec.batch_id.fee_structure_ids if rec.batch_id else self.env['fee.structure']

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        self.fee_structure_id = False
        self.fee_type_display = ''
        self.total_fee_display = 0.0
        self.grand_total_display = 0.0
        self.installment_summary = ''

    @api.onchange('fee_structure_id', 'batch_id')
    def _onchange_fee_structure(self):
        if not self.fee_structure_id:
            self.fee_type_display = ''
            self.total_fee_display = 0.0
            self.base_fee_display = 0.0
            self.gst_display = 0.0
            self.admission_fee_display = 0.0
            self.grand_total_display = 0.0
            self.gst_rate_display = ''
            self.installment_summary = ''
            return

        fs = self.fee_structure_id
        fee_type_labels = dict([
            ('lumpsum', 'Lump Sum'), ('installment', 'Installment'),
            ('monthly', 'Monthly'), ('quarterly', 'Quarterly'),
            ('semi_annual', 'Semi-Annual'), ('annual', 'Annual'),
            ('admission', 'Admission Fee'), ('exam', 'Exam Fee'),
            ('material', 'Material Fee'), ('registration', 'Registration Fee'),
        ])
        self.fee_type_display = fee_type_labels.get(fs.fee_type, fs.fee_type)
        self.gst_rate_display = dict([
            ('0', '0%'), ('5', '5%'), ('12', '12%'), ('18', '18%'), ('28', '28%'),
        ]).get(fs.gst_rate, '')

        if fs.fee_type == 'installment':
            self.total_fee_display = fs.total_fee_amount
            self.base_fee_display = round(fs.total_fee_amount / (1 + float(fs.gst_rate or 0) / 100), 2)
            self.gst_display = round(self.total_fee_display - self.base_fee_display, 2)
        else:
            self.total_fee_display = fs.amount_inclusive
            self.base_fee_display = fs.amount_exclusive
            self.gst_display = fs.tax_amount

        admission = self.batch_id.fee_structure_ids.filtered(lambda f: f.fee_type == 'admission')
        adm_fee = sum(admission.mapped('amount_inclusive'))
        self.admission_fee_display = adm_fee
        self.grand_total_display = self.total_fee_display + adm_fee

        if fs.fee_type == 'installment' and fs.installment_ids:
            lines = [f"{'Installment':<22} {'Due Date':<14} {'Amount (₹)':>12}"]
            lines.append('─' * 50)
            for inst in fs.installment_ids.sorted('sequence'):
                due = str(inst.due_date) if inst.due_date else 'TBD'
                lines.append(f"{inst.name:<22} {due:<14} {inst.amount_inclusive:>12,.2f}")
            lines.append('─' * 50)
            lines.append(f"{'TOTAL':<22} {'':14} {fs.total_fee_amount:>12,.2f}")
            self.installment_summary = '\n'.join(lines)
        else:
            self.installment_summary = ''

    def _map_district(self, lead):
        if not lead.district or lead.district in ('nil', 'other', 'abroad'):
            return False
        return DISTRICT_MAP.get(lead.district, lead.district.title())

    def _map_branch(self, lead):
        if lead.admission_branch:
            key = lead.admission_branch.strip().lower()
            if key in BRANCH_MAP:
                return BRANCH_MAP[key]
        return 'kochi'

    def _map_logic_join(self, lead):
        source_name = (lead.leads_source.name or '').lower() if lead.leads_source else ''
        if 'seminar' in source_name:
            return 'seminar'
        if lead.incoming_source == 'social_media' or lead.digital_lead:
            return 'social_media'
        if lead.referred_by:
            return 'reference'
        if lead.incoming_source == 'google' or lead.digital_lead_source == 'google':
            return 'ads'
        return False

    def _resolve_course_ids(self, lead):
        Course = self.env['course.master']
        course_ids = []
        for course in lead.course_inter:
            match = Course.search([('name', '=ilike', course.name)], limit=1)
            if match:
                course_ids.append(match.id)
        return course_ids

    def _prepare_student_vals(self):
        self.ensure_one()
        lead = self.lead_id
        admission_officer = False
        if lead.lead_owner and lead.lead_owner.user_id:
            admission_officer = lead.lead_owner.user_id.id

        vals = {
            'name': lead.student_name or lead.name,
            'lead_reference_no': lead.reference_no,
            'email': lead.email_address,
            'phone': lead.phone_number,
            'whatsapp_number': lead.parent_number or lead.phone_number_second,
            'father_phone': lead.parent_number,
            'district': self._map_district(lead),
            'city': lead.place,
            'college': lead.college_name,
            'qualification': lead.lead_qualification,
            'batch_id': self.batch_id.id,
            'branch': self._map_branch(lead),
            'admission_officer_id': admission_officer,
            'joining_status': 'new',
            'lead_id': lead.id,
        }
        logic_join = self._map_logic_join(lead)
        if logic_join:
            vals['logic_join'] = logic_join

        course_ids = self._resolve_course_ids(lead)
        if course_ids:
            vals['course_ids'] = [(6, 0, course_ids)]
        return vals

    def action_confirm_admission(self):
        self.ensure_one()
        lead = self.lead_id

        if lead.student_profile_created or lead.student_id:
            raise ValidationError(_('A student profile already exists for this lead.'))

        # ── Simple mode (batch not required) ─────────────────────────────
        if not self.batch_required:
            lead.write({
                'admission_status':   True,
                'admission_date':     fields.Datetime.now(),
                'lead_quality':       'admission',
                'state':              'qualified',
                'current_status':     'admission',
            })
            lead.message_post(body=_('✅ Admission confirmed for %s.') % lead.name)
            return {'type': 'ir.actions.act_window_close'}

        # ── Full mode (batch + fee required) ─────────────────────────────
        if not self.batch_id:
            raise ValidationError(_('Please select a batch to complete admission.'))
        if not self.fee_structure_id:
            raise ValidationError(_('Please select a fee structure to complete admission.'))

        student = self.env['student.details'].create(self._prepare_student_vals())

        fs = self.fee_structure_id
        total = fs.total_fee_amount if fs.fee_type == 'installment' else fs.amount_inclusive
        admission = self.batch_id.fee_structure_ids.filtered(lambda f: f.fee_type == 'admission')
        adm_total = sum(admission.mapped('amount_inclusive'))
        grand_total = total + adm_total

        enrollment = self.env['student.enrollment'].create({
            'student_id': student.id,
            'batch_id': self.batch_id.id,
            'fee_structure_id': self.fee_structure_id.id,
            'total_fee': grand_total,
            'fee_type': fs.fee_type,
            'gst_rate': fs.gst_rate,
        })

        if lead.admission_amount and lead.admission_amount > 0:
            if enrollment:
                self.env['student.fee.payment'].create({
                    'enrollment_id': enrollment.id,
                    'amount': lead.admission_amount,
                    'payment_date': lead.date_of_receipt or fields.Date.today(),
                    'receipt_no': lead.receipt_no,
                    'remarks': _('Admission fee from lead %s') % (lead.reference_no or lead.name),
                })

        lead.write({
            'student_id': student.id,
            'adm_id': student.id,
            'student_profile_created': True,
            'admission_status': True,
            'admission_date': fields.Datetime.now(),
            'lead_quality': 'admission',
            'state': 'qualified',
            'current_status': 'admission',
            'admission_batch': self.batch_id.name,
            'student_name': student.name,
        })
        lead.message_post(body=_(
            'Student admission completed. Registration No: %s, Lead Ref: %s, Batch: %s, Fee Plan: %s'
        ) % (
            student.registration_no,
            student.lead_reference_no or lead.reference_no,
            self.batch_id.name,
            self.fee_structure_id.name,
        ))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Student Details'),
            'res_model': 'student.details',
            'view_mode': 'form',
            'res_id': student.id,
            'target': 'current',
        }
