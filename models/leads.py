from datetime import datetime, timedelta
import logging
import requests
from urllib.parse import quote
from odoo.http import request
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import html_escape
from markupsafe import Markup

_logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Model: lead.assignment.history
# --------------------------------------------------------------------------
class LeadAssignmentHistory(models.Model):
    _name = 'lead.assignment.history'
    _description = 'Lead Assignment History'
    _order = 'create_date desc'

    lead_id = fields.Many2one('leads.logic', string='Lead', ondelete='cascade')
    owner_id = fields.Many2one('hr.employee', string='Assigned Officer')
    assigned_date = fields.Datetime(string='Assigned Date', default=fields.Datetime.now)
    assigned_by = fields.Many2one('res.users', string='Assigned By', default=lambda self: self.env.user)


# --------------------------------------------------------------------------
# Model: lead.quality.history
# --------------------------------------------------------------------------
class LeadQualityHistory(models.Model):
    _name = 'lead.quality.history'
    _description = 'Lead Quality History'
    _order = 'create_date desc'

    lead_id = fields.Many2one('leads.logic', string='Lead', ondelete='cascade')
    lead_quality = fields.Selection(
        [
            ('new', '🆕  New'),
            ('first_attempt', '🎯 First Attempt'),
            ('waiting_for_admission', '⏳  Waiting for Admission'),
            ('admission', '🎓  Admission'),
            ('hot', '🔥  Hot'),
            ('warm', '🌞  Warm'),
            ('cold', '❄️  Cold'),
            ('not_responding', '🔕  Ringing Not Responding'),
            ('call_later', '📞  Call Back'),
            ('follow_up', '⏰  Follow Up'),
            ('not_reachable', '⏳ Busy'),
            ('wrong_number', '📵 Wrong number'),
            ('not_interested', '❌ Not Interested'),
            ('not_attended', '📵Not Attended'),
            ('already_joined', '✅ Already Joined'),
        ],
        string='Lead Quality'
    )
    user_id = fields.Many2one('res.users', string='Changed By', default=lambda self: self.env.user)
    change_date = fields.Datetime(string='Change Date', default=fields.Datetime.now)


# --------------------------------------------------------------------------
# Model: leads.logic  (Main Lead Model)
# --------------------------------------------------------------------------
class LeadsForm(models.Model):
    _name = 'leads.logic'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Leads'
    _rec_name = 'name'
    _order = 'id desc'

    # ── Basic Information ──────────────────────────────────────────────────
    leads_source = fields.Many2one('leads.sources', string='Leads Source', required=True)
    source_name = fields.Char(string="Source", related="leads_source.name")
    name = fields.Char(string='Lead Name', required=True)
    email_address = fields.Char(string='Email')
    phone_number = fields.Char(string='Mobile', required=True)
    probability = fields.Float(string='Probability')
    admission_status = fields.Boolean(string='Admission', readonly=True)
    date_of_adding = fields.Date(string='Date of Adding', default=fields.Date.today, readonly=True)
    last_update_date = fields.Datetime(string='Last Updated Date', default=fields.Datetime.now)
    reference_no = fields.Char(
        "Reference",
        default=lambda self: _('New'),
        copy=False,
        readonly=True,
        tracking=True
    )
    lead_creator_id = fields.Many2one(
        'res.users',
        string='Lead Creator',
        readonly=True,
        copy=False,
        index=True,
        help='User who created this lead.',
    )
    is_editable = fields.Boolean(string="Editable", default=False)

    # ── Phone Masking ──────────────────────────────────────────────────────
    masked_phone = fields.Char(string="Phone", compute="_compute_masked_phone")
    show_phone = fields.Boolean(default=False)

    @api.depends('phone_number', 'show_phone')
    def _compute_masked_phone(self):
        for rec in self:
            if rec.show_phone:
                rec.masked_phone = rec.phone_number or ''
            else:
                if rec.phone_number and len(rec.phone_number) >= 10:
                    rec.masked_phone = 'XXXXXX' + rec.phone_number[-4:]
                else:
                    rec.masked_phone = 'Hidden'

    def action_toggle_phone(self):
        for rec in self:
            rec.show_phone = not rec.show_phone

    # ── Lead Open Tracking ─────────────────────────────────────────────────
    open_count = fields.Integer(string="Open Count", default=0)
    last_opened_on = fields.Datetime(string="Last Opened On")
    last_opened_by = fields.Many2one('res.users', string="Last Opened By")
    open_history_ids = fields.One2many('lead.open.history', 'lead_id', string='Open History')

    def web_read(self, specification):
        res = super(LeadsForm, self).web_read(specification)
        if len(self) == 1 and isinstance(self.id, int):
            try:
                ip_addr = 'Internal/Unknown'
                if request:
                    ip_addr = request.httprequest.remote_addr or 'Internal/Unknown'
                self.env['lead.open.history'].sudo().create({
                    'lead_id': self.id,
                    'user_id': self.env.user.id,
                    'opened_on': fields.Datetime.now(),
                    'ip_address': ip_addr,
                    'remarks': _('Lead Form Accessed via Web Client')
                })
                self.sudo().write({
                    'last_opened_on': fields.Datetime.now(),
                    'last_opened_by': self.env.user.id,
                    'open_count': self.open_count + 1
                })
            except Exception as e:
                _logger.error("AUDIT ERROR: %s", str(e))
        return res

    # ── Write Override ─────────────────────────────────────────────────────
    def write(self, vals):
        if 'phone_number' in vals:
            vals['phone_number'] = vals['phone_number'].replace(" ", "")

        if 'lead_owner' in vals and not self.env.context.get('skip_assignment_history'):
            for record in self:
                if vals['lead_owner'] != record.lead_owner.id:
                    self.env['lead.assignment.history'].create({
                        'lead_id': record.id,
                        'owner_id': vals['lead_owner'],
                        'assigned_date': fields.Datetime.now(),
                        'assigned_by': self.env.uid
                    })
                    vals['reassign_date'] = fields.Datetime.now()

        # ── Auto-compute quality from attendance % when it is being saved ──
        if 'attendance_percentage' in vals:
            pct = vals.get('attendance_percentage') or 0.0
            if pct > 75:
                vals['lead_quality'] = 'hot'
            elif pct > 50:
                vals['lead_quality'] = 'warm'
            elif pct > 30:
                vals['lead_quality'] = 'cold'
            else:
                vals['lead_quality'] = 'new'

        #if 'lead_quality' in vals:
            # Block manual quality change when attendance % is already stored
            # but allow attendance-driven quality (attendance_percentage is in vals too)
         #   if 'attendance_percentage' not in vals:
          #      for record in self:
           #         if record.attendance_percentage:
            #            vals.pop('lead_quality', None)
             #           break

            # Log quality history for records where quality actually changes
            if 'lead_quality' in vals:
                for record in self:
                    if vals.get('lead_quality') and vals['lead_quality'] != record.lead_quality:
                        self.env['lead.quality.history'].create({
                            'lead_id': record.id,
                            'lead_quality': vals['lead_quality'],
                            'user_id': self.env.uid,
                            'change_date': fields.Datetime.now()
                        })

        if 'call_response' in vals and vals['call_response']:
            response_obj = self.env['call.responses'].search([('name', '=', vals['call_response'])], limit=1)
            if not response_obj:
                response_obj = self.env['call.responses'].create({'name': vals['call_response']})
            if 'call_responses' in vals:
                vals['call_responses'].append((4, response_obj.id))
            else:
                vals['call_responses'] = [(4, response_obj.id)]
            vals['call_response'] = False

        res = super(LeadsForm, self).write(vals)
        if 'is_editable' not in vals:
            self.is_editable = False
        return res

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=100, order=None):
        domain = domain or []
        if name:
            domain = ['|', ('name', operator, name), ('phone_number', operator, name)] + domain
        return self._search(domain, limit=limit, order=order)

    # ── Lead Quality & Stage ───────────────────────────────────────────────
    lead_quality = fields.Selection(
        [
            ('new', '🆕  New'),
            ('first_attempt', '🎯 First Attempt'),
            ('waiting_for_admission', '⏳  Waiting for Admission'),
            ('admission', '🎓  Admission'),
            ('hot', '🔥  Hot'),
            ('warm', '🌞  Warm'),
            ('cold', '❄️  Cold'),
            ('not_responding', '🔕  Ringing Not Responding'),
            ('call_later', '📞  Call Back'),
            ('follow_up', '⏰  Follow Up'),
            ('not_reachable', '⏳ Busy'),
            ('wrong_number', '📵 Wrong number'),
            ('not_interested', '❌ Not Interested'),
            ('not_attended', '📵Not Attended'),
            ('already_joined', '✅ Already Joined'),
        ],
        string='Lead Quality', default='new', required=True, tracking=True
    )

    lead_stage_category = fields.Selection([
        ('funnel', 'FUNNEL'),
        ('prospects', 'PROSPECTS'),
        ('rnr_dnp', 'RNR / DNP'),
        ('admission_done', 'ADMISSION DONE'),
        ('re_try', 'RE-TRY'),
        ('alumni', 'ALUMNI'),
        ('junk', 'JUNK'),
    ], string='Stage Category', compute='_compute_lead_stage', store=True)

    @api.depends('lead_quality')
    def _compute_lead_stage(self):
        for record in self:
            quality = record.lead_quality
            if quality in ['hot', 'warm', 'cold', 'call_later', 'waiting_for_admission', 'already_joined']:
                record.lead_stage_category = 'prospects'
            elif quality in ['new', 'first_attempt', 'follow_up']:
                record.lead_stage_category = 'funnel'
            elif quality in ['not_interested']:
                record.lead_stage_category = 're_try'
            elif quality in ['not_responding', 'not_reachable', 'not_attended']:
                record.lead_stage_category = 'rnr_dnp'
            elif quality in ['admission', 'converted']:
                record.lead_stage_category = 'admission_done'
            elif quality in ['wrong_number']:
                record.lead_stage_category = 'junk'
            else:
                record.lead_stage_category = False

    hide_marketing_stages = fields.Boolean(string="Hide Toggle", default=False)
    marketing_button_label = fields.Char(compute="_compute_marketing_button_label")

    @api.depends('hide_marketing_stages')
    def _compute_marketing_button_label(self):
        for record in self:
            record.marketing_button_label = "Show Sales Guide" if record.hide_marketing_stages else "Hide Sales Guide"

    def action_toggle_marketing_info(self):
        for record in self:
            record.write({'hide_marketing_stages': not record.hide_marketing_stages})

    lost_reason = fields.Text(string="Lost Reason")
    crash_user_id = fields.Many2one('res.users', string="Crash User")
    lead_status = fields.Selection(
        [
            ('not_responding', 'Not Responding'),
            ('already_enrolled', 'Already Enrolled'),
            ('joined_in_another_institute', 'Joined in another institute'),
            ('nil', 'Nil'),
        ],
        string='Lead Status',
    )

    # ── Core Lead Fields ───────────────────────────────────────────────────
    place = fields.Char('Place')
    lead_owner = fields.Many2one('hr.employee', string='Lead Owner',
                                 default=lambda self: self.env.user.employee_id.id)
    seminar_lead_id = fields.Char()
    admission_date = fields.Datetime(string="Admission Date")
    phone_number_second = fields.Char(string='Phone Number')
    course_interested = fields.Char(string="Course Interested")
    seminar_id = fields.Integer(string="Seminar")
    preferred_course = fields.Char(string="Preferred Course")
    academic_year_of_course_attend = fields.Selection(
        [
            ('2023-2024', '2023-2024'), ('2024-2025', '2024-2025'),
            ('2025-2026', '2025-2026'), ('2026-2027', '2026-2027'),
        ],
        string="Academic Year of Course attended", default='2025-2026'
    )
    course_type = fields.Selection(
        [
            ('indian', 'Indian'), ('international', 'International'),
            ('crash', 'Crash'), ('repeaters', 'Repeaters'), ('nil', 'Nil'),
        ],
        string='Course Type'
    )
    state = fields.Selection(
        [
            ('new', 'New'), ('in_progress', 'In Progress'),
            ('qualified', 'Admission'), ('lost', 'Lost'),
        ],
        string='State', default='new', tracking=True
    )
    last_studied_course = fields.Char(string='Last Studied Course')
    incoming_source = fields.Selection(
        [
            ('social_media', 'Social Media'), ('google', 'Google'), ('hoardings', 'Hoardings'),
            ('tv_ads', 'TV Ads'), ('through friends', 'Through Friends'), ('whatsapp', 'WhatsApp'),
            ('re_admission', 'Re-Admission'), ('other', 'Other'),
        ],
        string='Incoming Calls / Walk In Source'
    )
    incoming_source_checking = fields.Boolean(string='Incoming Source Checking')
    academic_year = fields.Selection(
        [('2024-2025', '2024-2025'), ('2025-2026', '2025-2026'), ('2026-2027', '2026-2027'), ('nil', 'Nil')],
        string="Academic Year"
    )
    college_name = fields.Char(string='College/School')
    title = fields.Char(string="Title")
    lead_referral_staff_id = fields.Many2one('res.users', string='Lead Referral Staff')
    referred_by = fields.Selection(
        [('staff', 'Staff'), ('student', 'Student'), ('other', 'Other')],
        string='Referred By'
    )
    campaign = fields.Selection(
        [
            ('CA Weekend Thrissur', 'CA Weekend Thrissur'),
            ('CA Weekend Ernakulam', 'CA Weekend Ernakulam'),
            ('CA Weekend Trivandrum', 'CA Weekend Trivandrum'),
            ('CA Weekend Calicut', 'CA Weekend Calicut'),
            ('CA Weekend Perintalmanna', 'CA Weekend Perintalmanna'),
        ],
        string='Campaign'
    )
    country = fields.Selection(
        [
            ('india', 'India'), ('germany', 'Germany'), ('canada', 'Canada'), ('usa', 'USA'),
            ('australia', 'Australia'), ('italy', 'Italy'), ('france', 'France'),
            ('united_kingdom', 'United Kingdom'), ('saudi_arabia', 'Saudi Arabia'),
            ('ukraine', 'Ukraine'), ('united_arab_emirates', 'United Arab Emirates'),
            ('china', 'China'), ('japan', 'Japan'), ('singapore', 'Singapore'),
            ('indonesia', 'Indonesia'), ('russia', 'Russia'), ('oman', 'Oman'), ('nepal', 'Nepal'),
        ],
        string='Country', default='india'
    )
    referred_by_id = fields.Many2one('hr.employee', string='Referred Person')
    second_response = fields.Text(string="2nd Response")
    referred_by_name = fields.Char(string='Referred Person')
    referred_by_number = fields.Char(string='Referred Person Number')
    batch_preference = fields.Char(string='Batch Preference')
    tele_caller_id = fields.Many2one('res.users', string="Tele Caller")
    lead_qualification = fields.Selection(
        [
            ('plus_one_science', 'Plus One Science'), ('plus_two_science', 'Plus Two Science'),
            ('plus_two_commerce', 'Plus Two Commerce'), ('plus_one_commerce', 'Plus One Commerce'),
            ('commerce_degree', 'Commerce Degree'), ('other_degree', 'Other Degree'),
            ('working_professional', 'Working Professional'),
        ],
        string='Lead qualification'
    )
    adm_id = fields.Integer(string='Admission Id')
    student_id = fields.Many2one('student.details', string='Student', readonly=True, copy=False)
    district = fields.Selection(
        [
            ('wayanad', 'Wayanad'), ('ernakulam', 'Ernakulam'), ('kollam', 'Kollam'),
            ('thiruvananthapuram', 'Thiruvananthapuram'), ('kottayam', 'Kottayam'),
            ('kozhikode', 'Kozhikode'), ('palakkad', 'Palakkad'), ('kannur', 'Kannur'),
            ('alappuzha', 'Alappuzha'), ('malappuram', 'Malappuram'), ('kasaragod', 'Kasaragod'),
            ('thrissur', 'Thrissur'), ('idukki', 'Idukki'), ('pathanamthitta', 'Pathanamthitta'),
            ('abroad', 'Abroad'), ('other', 'Other'), ('nil', 'Nil'),
        ],
        string='District'
    )
    referred_teacher = fields.Many2one('res.users', string='Referred Teacher')
    over_due = fields.Boolean(string='Over Due')
    next_follow_up_date = fields.Date(string="Next Follow Up Date")
    remarks = fields.Char(string='Remarks')
    parent_number = fields.Char('Parent Number')
    closing_date = fields.Date(string="Closing Date")
    call_responses = fields.Many2many('call.responses', string="Call Responses",
                                      compute='_compute_total_responses', store=True)
    third_response = fields.Text(string="Last Response")
    mode_of_study = fields.Selection(
        [('online', 'Online'), ('offline', 'Offline'), ('nil', 'Nil')],
        string='Mode of Study'
    )
    company_id = fields.Many2one(
        string='Company', comodel_name='res.company', required=True,
        default=lambda self: self.env.company
    )
    assigned_date = fields.Date(string='Assigned Date', compute="_compute_lead_owner", store=True)
    reassign_date = fields.Datetime(string='Reassign Date', readonly=True)

    # ── Team (auto-resolved from lead_owner's team membership) ────────────
    team_id = fields.Many2one(
        'lead.team', string='Team',
        compute='_compute_team_id', store=True,
        help='Team automatically set from the lead owner\'s team membership.'
    )

    @api.depends('lead_owner')
    def _compute_team_id(self):
        for rec in self:
            if rec.lead_owner:
                # 1. Check if owner is a regular team member
                member = self.env['lead.team.member'].search(
                    [('employee_id', '=', rec.lead_owner.id)], limit=1
                )
                if member:
                    rec.team_id = member.team_id
                else:
                    # 2. Check if owner is a team lead
                    team = self.env['lead.team'].search(
                        [('team_lead_ids', '=', rec.lead_owner.id),
                         ('active', '=', True)], limit=1
                    )
                    rec.team_id = team if team else False
            else:
                rec.team_id = False
    assignment_history_ids = fields.One2many('lead.assignment.history', 'lead_id',
                                              string='Assignment History', readonly=True)
    quality_history_ids = fields.One2many('lead.quality.history', 'lead_id',
                                           string='Lead Quality History', readonly=True)
    digital_lead = fields.Boolean(string="Digital Lead")
    digital_lead_source = fields.Selection(
        [
            ('just_dial', 'Just Dial'), ('youtube_google', 'Youtube - Google'),
            ('whatsapp_campaign', 'Whatsapp Campaign'), ('messenger', 'Messenger'),
            ('facebook', 'Facebook'), ('linkedin', 'Linkedin'), ('instagram', 'Instagram'),
            ('whatsapp_meta', 'Whatsapp Meta'), ('website', 'Website'), ('google', 'Google'),
        ],
        string="Digital Lead Source"
    )
    platform = fields.Selection(
        [
            ('facebook', 'Facebook'), ('instagram', 'Instagram'), ('website', 'Website'),
            ('just_dial', 'Just Dial'), ('other', 'Other'),
        ],
        string='Platform'
    )
    expected_joining_date = fields.Date(string="Expected Joining Date")
    not_response_note = fields.Text(string="Not Respond Reason")
    current_status = fields.Selection(
        [
            ('new_lead', 'New Lead'), ('not_responding', 'Not Responding'),
            ('need_follow_up', 'Need Follow-Up'), ('admission', 'Admission'), ('lost', 'Lost'),
        ],
        string="Current Status", default="new_lead"
    )
    call_response = fields.Text(string="Response")
    transitions = fields.Selection(
        [
            ('future_lead', 'Future Lead'), ('junk_lead', 'Junk Lead'),
            ('not_qualified', 'Not Qualified'), ('qualified', 'Qualified'),
        ],
        string="Transitions", tracking=True
    )
    sample = fields.Char(string='Sample', compute='get_phone_number_for_whatsapp')
    sended_welcome_mail = fields.Boolean(string="Sended Welcome Mail")
    receipt_no = fields.Char(string="Receipt No.")
    admission_amount = fields.Float(string="Admission Fee")
    date_of_receipt = fields.Date(string="Date of Receipt")
    student_profile_created = fields.Boolean(string="Student Profile Created")
    crash_lead = fields.Boolean(string="Crash Lead")
    stream = fields.Char(string="Stream")
    digital_head_id = fields.Many2one('res.users', string='Digital Head')
    response_ids = fields.One2many('lead.response', 'lead_id', string="Responses")
    course_inter = fields.Many2many('course.interested', string="Course Interested In")
    call_log_ids = fields.One2many("lead.call.log", "lead_id", string="Call History")
    followup_ids = fields.One2many('lead.followup', 'lead_id', string="Follow Ups")

    # ── Admission fields (standalone, no openeducat) ───────────────────────
    admission_batch = fields.Char(string="Batch")
    admission_branch = fields.Char(string="Branch")
    admission_course = fields.Char(string="Course")
    admission_fee_paid = fields.Boolean(string="Admission Fee Paid")
    re_allocation_date = fields.Date(string="Re Allocation Date")
    batch_fee = fields.Float(string="Expected Revenue")
    booking_amount = fields.Float(string="Booking Amount")
    student_name = fields.Char(string="Student Name")

    # ── Attendance Percentage ──────────────────────────────────────────────
    attendance_percentage = fields.Float(string="Attendance %", digits=(5, 2))

    @api.onchange('attendance_percentage')
    def _onchange_attendance_percentage(self):
        for rec in self:
            pct = rec.attendance_percentage or 0.0
            if pct > 75:
                rec.lead_quality = 'hot'
            elif pct > 50:
                rec.lead_quality = 'warm'
            elif pct > 30:
                rec.lead_quality = 'cold'
            else:
                rec.lead_quality = 'new'

    # ── Course Interest Computed Flags ─────────────────────────────────────
    is_ca_inter_selected = fields.Boolean(compute="_compute_course_selection")
    is_ca_selected = fields.Boolean(compute="_compute_course_selection")

    
    @api.depends('course_inter.name')
    def _compute_course_selection(self):
        for rec in self:
            selected_names = set(rec.course_inter.mapped('name'))
            rec.is_ca_inter_selected = 'CA INTER' in selected_names
            rec.is_ca_selected = 'CA' in selected_names

    # ── Stage Completion Flags ─────────────────────────────────────────────
    stage1_completed = fields.Boolean(compute='_compute_stage1_completed', store=True)
    stage2_completed = fields.Boolean(compute='_compute_stage2_completed', store=True)
    stage3_completed = fields.Boolean(compute='_compute_stage3_completed', store=True)
    stage4_completed = fields.Boolean(compute='_compute_stage4_completed', store=True)
    stage5_completed = fields.Boolean(compute='_compute_stage5_completed', store=True)
    stage6_completed = fields.Boolean(compute='_compute_stage6_completed', store=True)
    stage7_completed = fields.Boolean(compute='_compute_stage7_completed', store=True)

    @api.depends('course_inter')
    def _compute_stage1_completed(self):
        for rec in self:
            rec.stage1_completed = bool(rec.first_call and rec.webinar_invite_sent)

    @api.depends('course_inter')
    def _compute_stage2_completed(self):
        for rec in self:
            rec.stage2_completed = False

    @api.depends('course_inter')
    def _compute_stage3_completed(self):
        for rec in self:
            rec.stage3_completed = False

    @api.depends('course_inter')
    def _compute_stage4_completed(self):
        for rec in self:
            rec.stage4_completed = False

    @api.depends('course_inter')
    def _compute_stage5_completed(self):
        for rec in self:
            rec.stage5_completed = False

    @api.depends('course_inter')
    def _compute_stage6_completed(self):
        for rec in self:
            rec.stage6_completed = False

    @api.depends('course_inter')
    def _compute_stage7_completed(self):
        for rec in self:
            rec.stage7_completed = False

    # ── Progress HTML ──────────────────────────────────────────────────────
    progress_html = fields.Html(compute='_compute_progress_html', sanitize=False)

    @api.depends(
        'course_inter', 'course_inter.name', 'first_call', 'webinar_invite_sent',
        'stage1_completed', 'stage2_completed', 'stage3_completed', 'stage4_completed',
        'stage5_completed', 'stage6_completed', 'stage7_completed',
    )
    def _compute_progress_html(self):
        for rec in self:
            stages = [
                ('Stage 1', '📞', rec.stage1_completed),
                ('Stage 2', '📚', rec.stage2_completed),
                ('Stage 3', '🎓', rec.stage3_completed),
                ('Stage 4', '🏆', rec.stage4_completed),
                ('Stage 5', '💼', rec.stage5_completed),
                ('Stage 6', '🎁', rec.stage6_completed),
                ('Stage 7', '🤝', rec.stage7_completed),
            ]
            html = '<div class="crm-progress-wrapper"><div class="crm-progress-row" style="display:flex;flex-wrap:nowrap;align-items:flex-start;gap:0;overflow-x:auto;min-width:max-content;">'
            for i, (label, icon, done) in enumerate(stages):
                circle_class = "progress-circle done" if done else (
                    "progress-circle active" if (i == 0 or stages[i - 1][2]) else "progress-circle")
                html += f'<div class="progress-step" style="display:flex;flex-direction:column;align-items:center;min-width:80px;text-align:center;"><div class="{circle_class}" style="margin-bottom:6px;">{"✓" if done else icon}</div><div class="progress-label">{label}</div></div>'
                if i < len(stages) - 1:
                    line_class = "progress-line done" if done else "progress-line"
                    html += f'<div class="{line_class}" style="margin-top:24px;flex-shrink:0;align-self:flex-start;"></div>'
            html += '</div></div>'
            rec.progress_html = html

        # ── Touch Point Fields ─────────────────────────────────────────────────
    first_call = fields.Boolean(string="First Call", default=False)
    first_call_dt = fields.Datetime(string="First Call Date")
    whatsapp_intro = fields.Boolean(string="WhatsApp Intro Message", default=False)
    whatsapp_date = fields.Datetime(string="WhatsApp Date")
    results_highlights = fields.Boolean(string="Results Highlights", default=False)
    results_highlights_dt = fields.Datetime(string="Results Highlights Date")
    second_followup = fields.Boolean(string="Second Follow Up Call", default=False)
    second_followup_dt = fields.Datetime(string="Second Follow Up Date")
    course_wise_webinar = fields.Boolean(string="Course Wise Webinar", default=False)
    course_wise_webinar_dt = fields.Datetime(string="Course Wise Webinar Date")
    webinar_followup = fields.Boolean(string="Webinar Follow Up Call", default=False)
    webinar_followup_dt = fields.Datetime(string="Webinar Follow Up Date")
    testimonials = fields.Boolean(string="Testimonials", default=False)
    testimonials_dt = fields.Datetime(string="Testimonials Date")
    placements = fields.Boolean(string="Placements", default=False)
    placements_dt = fields.Datetime(string="Placements Date")
    logic_events = fields.Boolean(string="Logic Events", default=False)
    logic_events_dt = fields.Datetime(string="Logic Events Date")
    retargeting = fields.Boolean(string="Retargeting", default=False)
    retargeting_dt = fields.Datetime(string="Retargeting Date")
    third_follow_up = fields.Boolean(string="Third Follow Up", default=False)
    third_follow_up_dt = fields.Datetime(string="Third Follow Up Date")
    fourth_follow_up = fields.Boolean(string="Fourth Follow Up", default=False)
    fourth_follow_up_dt = fields.Datetime(string="Fourth Follow Up Date")
    closing = fields.Boolean(string="Closing", default=False)
    closing_dt = fields.Datetime(string="Closing Date Field")
    zoom_schedule_dt = fields.Datetime(string="Zoom Schedule Date", tracking=True)
    walkin_schedule_dt = fields.Datetime(string="Walk-in Schedule Date", tracking=True)
    second_follow_up = fields.Boolean(string="Second Follow Up", default=False)
    second_follow_up_dt = fields.Datetime(string="Second Follow Up Date")
    sent_webinar = fields.Boolean(string="Sent Webinar", default=False)
    sent_webinar_dt = fields.Datetime(string="Sent Webinar Date")
    third_call = fields.Boolean(string="Third Call", default=False)
    third_call_dt = fields.Datetime(string="Third Call Date")
    touches_complete = fields.Boolean(string="Touches Complete", default=False)
    touches_complete_dt = fields.Datetime(string="Touches Complete Date")

    # ── Webinar Fields ─────────────────────────────────────────────────────
    webinar_invite_sent = fields.Boolean(string="Webinar Invite Sent", default=False)
    webinar_invite_sent_on = fields.Datetime(string="Webinar Invite Sent On")
    webinar_invite_sent_by = fields.Many2one('res.users', string="Webinar Invite Sent By")
    webinar_zoom_link = fields.Char(string="Webinar Zoom Link")

    # ── Extra ──────────────────────────────────────────────────────────────
    updated_remarks = fields.Text(string="Updated Remarks")
    truncated_call_response = fields.Char(string="Truncated Response", compute="_compute_truncated_response")
    is_team_leader = fields.Boolean(compute="_compute_team_leader")
    is_forwarded = fields.Boolean(string="Forwarded", default=False, tracking=True)

    # ── Call Responses ─────────────────────────────────────────────────────
    @api.depends()
    def _compute_total_responses(self):
        pass  # populated via write override

    # ── Computed helpers ───────────────────────────────────────────────────
    def _compute_truncated_response(self):
        for record in self:
            record.truncated_call_response = (record.call_response[:20] + "...") if record.call_response else ""

    @api.depends()
    def _compute_team_leader(self):
        for record in self:
            record.is_team_leader = self.env.user.has_group('custom_leads_19.group_lead_team_lead')

    @api.depends('lead_owner')
    def _compute_lead_owner(self):
        for rec in self:
            if rec.lead_owner:
                rec.assigned_date = fields.Datetime.now()

    def get_phone_number_for_whatsapp(self):
        for rec in self:
            if rec.phone_number:
                # Use wa.me (universal deep-link):
                #   Mobile  → triggers "Open in WhatsApp" / opens app directly
                #   Desktop → opens WhatsApp Web
                # Strip leading + so wa.me gets a clean international number
                clean = rec.phone_number.replace('+', '').replace(' ', '')
                rec.sample = "https://wa.me/" + clean
            else:
                rec.sample = ''

    # ── WhatsApp Helpers ───────────────────────────────────────────────────
    def _send_whatsapp_link(self, boolean_field, date_field, message):
        self.ensure_one()
        phone = (self.phone_number or '').replace('+', '').replace(' ', '')
        if not phone:
            return
        if getattr(self, boolean_field):
            return
        whatsapp_url = "https://wa.me/%s?text=%s" % (phone, quote(message))
        self.write({boolean_field: True, date_field: fields.Datetime.now()})
        return {'type': 'ir.actions.act_url', 'url': whatsapp_url, 'target': 'new'}

    # ── Webinar Wizard ─────────────────────────────────────────────────────
    def action_open_webinar_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send Webinar Invite',
            'res_model': 'webinar.invite.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    # ── Lead Actions ───────────────────────────────────────────────────────
    def action_schedule_meeting(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Schedule Meeting',
            'res_model': 'leads.schedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }


    def action_open_funnel_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lead Funnel',
            'res_model': 'leads.funnel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def action_open_confirm_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Open Lead?',
            'res_model': 'leads.confirm.wizard',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def action_voxbay_call(self):
        self.ensure_one()
        if not self.phone_number:
            raise UserError("Lead does not have a phone number.")
        company = self.env.company
        uid = company.voxbay_uid
        upin = company.voxbay_upin
        callerid = company.voxbay_callerid
        if not all([uid, upin, callerid]):
            raise UserError("Voxbay API credentials are not configured in Company Settings.")
        user_no = self.env.user.voxbay_user_no
        if not user_no:
            raise UserError("Your Voxbay Extension Number is not configured in your User Profile.")
        destination = self.phone_number.strip().replace(" ", "").replace("+", "")
        url = f"https://x.voxbay.com/api/click_to_call?id_dept=0&uid={uid}&upin={upin}&user_no={user_no}&destination={destination}&callerid={callerid}&"
        try:
            response = requests.get(url, timeout=10)
            api_status = f"HTTP {response.status_code}\nResponse: {response.text}"
            call_log = self.env["lead.call.log"].create(
                {"lead_id": self.id, "user_id": self.env.user.id, "call_time": fields.Datetime.now(), "remarks": "Initiated via Voxbay"})

            # ── Auto-complete queue entry on Voxbay call ──────────────────
            today = fields.Date.today()
            if self.daily_queue_date == today and not self.daily_call_done:
                same_group = self.search([
                    ('lead_owner', '=', self.lead_owner.id),
                    ('lead_quality', '=', self.lead_quality),
                    ('daily_queue_date', '=', today),
                    ('id', '!=', self.id),
                ])
                max_seq = max(same_group.mapped('daily_call_sequence') or [0])
                self.write({
                    'daily_call_done': True,
                    'daily_call_time': fields.Datetime.now(),
                    'daily_call_sequence': max_seq + 1,
                    'daily_call_count': self.daily_call_count + 1,
                })

            wizard = self.env['voxbay.call.wizard'].create(
                {'lead_id': self.id, 'api_response': api_status, 'call_log_id': call_log.id})
            return {'name': 'Voxbay Call Status', 'type': 'ir.actions.act_window', 'res_model': 'voxbay.call.wizard',
                    'res_id': wizard.id, 'view_mode': 'form', 'target': 'new'}
        except Exception as e:
            raise UserError(f"Failed to connect to Voxbay API:\n{str(e)}")

    def action_bonvoice_call(self):
        self.ensure_one()
        if not self.phone_number:
            raise UserError("Lead does not have a phone number.")
        company = self.env.company
        username = company.bonvoice_username
        password = company.bonvoice_password
        api_url = company.bonvoice_url or 'https://backend.pbx.bonvoice.com/autoDialManagement/autoCallBridging/'
        leg_a_cid = company.bonvoice_leg_a_caller_id
        leg_b_cid = company.bonvoice_leg_b_caller_id
        if not all([username, password]):
            raise UserError("Bourn Voice API credentials are not configured in Company Settings.")
        agent_no = self.env.user.bonvoice_agent_number
        if not agent_no:
            raise UserError("Your Bourn Voice Agent Number is not configured in your User Profile.")
        destination = self.phone_number.strip().replace(" ", "").replace("+", "")
        try:
            auth_url = "https://backend.pbx.bonvoice.com/usermanagement/external-auth/"
            auth_response = requests.post(auth_url, json={"username": username, "password": password}, timeout=10)
            if auth_response.status_code != 200:
                raise UserError(f"Bourn Voice Auth Failed:\n{auth_response.text}")
            auth_data = auth_response.json()
            if auth_data.get('status') != '1':
                raise UserError(f"Bourn Voice Auth Error:\n{auth_data.get('message', 'Unknown Error')}")
            token = auth_data.get('data', {}).get('token')
            if not token:
                raise UserError("Bourn Voice Auth Error: No token returned.")
            headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
            call_payload = {
                "autocallType": "3", "destination": agent_no, "ringStrategy": "ringall",
                "legACallerID": leg_a_cid or agent_no, "legAChannelID": "1", "legADialAttempts": "1",
                "legBDestination": destination, "legBCallerID": leg_b_cid or agent_no,
                "legBChannelID": "1", "legBDialAttempts": "1",
                "eventID": f"ld{self.id}{fields.Datetime.now().strftime('%M%S')}"[:16],
                "callBackParams": {"lead_id": str(self.id)[:50], "agent_id": str(self.env.user.id)[:50]}
            }
            call_response = requests.post(api_url, json=call_payload, headers=headers, timeout=10)
            api_status = f"HTTP {call_response.status_code}\nResponse: {call_response.text}"
            call_log = self.env["lead.call.log"].create(
                {"lead_id": self.id, "user_id": self.env.user.id, "call_time": fields.Datetime.now(), "remarks": "Initiated via Bourn Voice"})
            wizard = self.env['voxbay.call.wizard'].create(
                {'lead_id': self.id, 'api_response': api_status, 'call_log_id': call_log.id})
            return {'name': 'Bourn Voice Call Status', 'type': 'ir.actions.act_window',
                    'res_model': 'voxbay.call.wizard', 'res_id': wizard.id, 'view_mode': 'form', 'target': 'new'}
        except requests.exceptions.RequestException as e:
            raise UserError(f"Failed to connect to Bourn Voice API:\n{str(e)}")

    def action_send_whatsapp_intro(self):
        for record in self:
            if not record.phone_number:
                raise UserError("Phone number is missing!")
            full_phone = record.phone_number.strip().replace(" ", "")
            record.whatsapp_intro = True
            record.whatsapp_date = fields.Datetime.now()
            url = "https://backend.aisensy.com/campaign/t1/api/v2"
            payload = {
                "apiKey": "YOUR_AISENSY_API_KEY",
                "campaignName": "odoo19test",
                "destination": full_phone,
                "userName": record.name or "",
            }
            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code != 200:
                    raise UserError(f"WhatsApp API error: {response.status_code}\n{response.text}")
            except Exception as e:
                raise UserError(f"Failed to send WhatsApp message:\n{str(e)}")
            record.message_post(body=f"📩 WhatsApp intro sent to {full_phone} via AiSensy")
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_add_followup(self):
        self.ensure_one()
        if not self.id:
            raise UserError(_("Please save the lead before adding a follow-up."))
        return {
            'name': _('Add Follow-Up'),
            'type': 'ir.actions.act_window',
            'res_model': 'lead.followup.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_lead_id': self.id,
                'active_id': self.id,
            },
        }

    def action_add_call_log(self):
        for record in self:
            self.env["lead.call.log"].create(
                {"lead_id": record.id, "user_id": self.env.user.id, "call_time": fields.Datetime.now()})
            record.message_post(
                body=f"📞 Call logged by {self.env.user.name} on {fields.Datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")

    def whatsapp_click_button(self):
        return {'type': 'ir.actions.act_url', 'name': "Leads Whatsapp", 'target': 'new', 'url': self.sample}

    def act_attempt_to_connect(self):
        for record in self:
            record.state = 'in_progress'
            record.first_call_dt = fields.Datetime.now()
            record.first_call = True
            record.lead_quality = 'first_attempt'

    def act_connected(self):
        return {'type': 'ir.actions.act_window', 'name': _('Connect'), 'res_model': 'connect.form', 'target': 'new',
                'view_mode': 'form', 'context': {'default_lead_id': self.id}}

    def act_not_connected(self):
        return {'type': 'ir.actions.act_window', 'name': _('Connect'), 'res_model': 'not.connect.form', 'target': 'new',
                'view_mode': 'form', 'context': {'default_lead_id': self.id}}

    def act_lost_lead(self):
        return {'type': 'ir.actions.act_window', 'name': _('Lost'), 'res_model': 'lost.lead.form', 'target': 'new',
                'view_mode': 'form', 'context': {'default_lead_id': self.id}}

    # ── Kanban quick actions ──────────────────────────────────────────────────

    def action_kanban_start_call(self):
        """Start timer overlay and open tel: link from Kanban.
        If 'Enable Call Timer Popup' is turned OFF in Settings, falls back to a
        plain tel: dial without opening the overlay.
        """
        self.ensure_one()
        param = self.env['ir.config_parameter'].sudo().get_param(
            'custom_leads_19.enable_call_timer'
        )
        if param == '0':
            # Timer disabled — dial directly and show response wizard
            phone = (self.phone_number or '').replace(' ', '')
            wizard_action = self.action_kanban_quick_response()
            return {
                'type': 'ir.actions.client',
                'tag': 'lead_direct_call',
                'params': {
                    'phone': phone,
                    'lead_id': self.id,
                    'wizard_action': wizard_action,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'lead_call_timer',
            'name': 'Call Timer',
            'params': {
                'lead_id': self.id,
                'lead_name': self.name,
                'phone': self.phone_number or '',
                'current_quality': self.lead_quality or 'new',
            },
        }

    def action_save_call_duration(self, duration_seconds):
        """Save completed call duration to call log. Returns log ID for recording attachment.
        Also auto-marks the lead as done in today's queue if it is queued for today.
        """
        self.ensure_one()
        mins = duration_seconds // 60
        secs = duration_seconds % 60
        duration_str = f"{mins:02d}:{secs:02d}"
        log = self.env['lead.call.log'].create({
            'lead_id': self.id,
            'user_id': self.env.user.id,
            'call_time': fields.Datetime.now(),
            'duration': duration_str,
            'call_type': 'outgoing',
            'remarks': f'Manual call via Kanban — Duration: {duration_str}',
        })
        self.message_post(
            body=f"📞 <b>Outgoing Call</b> to {self.phone_number} — Duration: <b>{duration_str}</b>"
        )

        # ── Auto-complete queue entry if this lead is in today's queue ────
        today = fields.Date.today()
        if self.daily_queue_date == today and not self.daily_call_done:
            same_group = self.search([
                ('lead_owner', '=', self.lead_owner.id),
                ('lead_quality', '=', self.lead_quality),
                ('daily_queue_date', '=', today),
                ('id', '!=', self.id),
            ])
            max_seq = max(same_group.mapped('daily_call_sequence') or [0])
            self.write({
                'daily_call_done': True,
                'daily_call_time': fields.Datetime.now(),
                'daily_call_sequence': max_seq + 1,
                'daily_call_count': self.daily_call_count + 1,
            })

        return log.id  # Return ID so JS can attach recording

    def action_kanban_quick_response(self):
        """Open quick response popup from Kanban card."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '📋 Response & Quality',
            'res_model': 'kanban.response.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_lead_id': self.id,
                'default_new_quality': self.lead_quality,
            },
        }

    def action_kanban_quick_quality(self):
        """Open quick quality change popup from Kanban card."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '🏷️ Change Quality',
            'res_model': 'kanban.quality.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_lead_id': self.id,
                'default_new_quality': self.lead_quality,
            },
        }

    def action_kanban_quick_followup(self):
        """Open follow-up wizard from Kanban card."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '⏰ Follow Up',
            'res_model': 'lead.followup.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_lead_id': self.id,
                'active_id': self.id,
            },
        }

    def act_transfer_to_waiting_for_admission(self):
        self.lead_quality = 'waiting_for_admission'

    def action_open_admission_wizard(self):
        self.ensure_one()
        if self.student_profile_created or self.student_id:
            raise UserError(_('A student profile already exists for this lead.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lead Admission'),
            'res_model': 'lead.admission.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def action_open_convert_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Convert Lead'),
            'res_model': 'convert.lead',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def action_view_student(self):
        self.ensure_one()
        if not self.student_id:
            raise UserError(_('No student profile linked to this lead yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Student Details'),
            'res_model': 'student.details',
            'view_mode': 'form',
            'res_id': self.student_id.id,
            'target': 'current',
        }

    def act_return_to_new_lead(self):
        self.state = 'new'

    def act_re_allocation_leads(self):
        selected_ids = self.env.context.get('active_ids', [])
        return {'type': 'ir.actions.act_window', 'name': _('Re Allocation'), 'res_model': 're.allocation.leads',
                'target': 'new', 'view_mode': 'form', 'context': {'default_leads_ids': [(6, 0, selected_ids)]}}

    def action_bulk_lead_allocation_tele_callers(self):
        active_ids = self.env.context.get('active_ids', [])
        return {'type': 'ir.actions.act_window', 'name': 'Allocation', 'res_model': 'allocation.tele_callers.wizard',
                'view_mode': 'form', 'target': 'new', 'context': {'parent_obj': active_ids}}

    def action_forward_lead(self):
        for rec in self:
            rec.is_forwarded = True

    def action_send_results_highlights(self):
        for record in self:
            record.results_highlights = True
            record.message_post(body="Results Highlight sent.")

    def action_second_followup(self):
        for record in self:
            record.second_followup = True
            record.second_followup_dt = fields.Datetime.now()
            record.message_post(body="Second Follow Up Completed.")

    # ── Constraints ────────────────────────────────────────────────────────
    @api.constrains('phone_number', 'academic_year_of_course_attend')
    def _check_duplicate_phone_number(self):
        for record in self:
            if record.phone_number and record.academic_year_of_course_attend:
                last_10_digits = record.phone_number[-10:]
                duplicate = self.sudo().search([
                    ('phone_number', 'like', '%' + last_10_digits),
                    ('academic_year_of_course_attend', '=', record.academic_year_of_course_attend),
                    ('id', '!=', record.id)
                ], limit=1)
                if duplicate:
                    lead_owner_name = duplicate.lead_owner.name if duplicate.lead_owner else "Unknown"
                    raise ValidationError(
                        _('The phone number %s already exists in academic year %s and is owned by %s.')
                        % (record.phone_number, record.academic_year_of_course_attend, lead_owner_name)
                    )

    # NOTE: previously required extra remarks when Lead Quality == 'bad_lead'
    # ('Language Barrier'). That quality value was removed from the
    # lead_quality selection, so this constraint no longer applies to anything
    # and has been dropped.

    # ── onchange ───────────────────────────────────────────────────────────
    @api.onchange('leads_source')
    def _onchange_leads_source(self):
        if self.leads_source:
            if 'incoming' in (self.source_name or '').lower() or 'walk in' in (self.source_name or '').lower():
                self.incoming_source_checking = True
            else:
                self.incoming_source_checking = False
                self.incoming_source = False
            if self.leads_source.digital_lead:
                self.digital_lead = True
            else:
                self.digital_lead = False
                self.digital_lead_source = False

    @api.onchange('phone_number')
    def _onchange_duplicate_phone_number(self):
        for record in self:
            if record.phone_number:
                last_10_digits = record.phone_number[-10:]
                duplicate = self.sudo().search(
                    [('phone_number', 'like', '%' + last_10_digits), ('id', '!=', self._origin.id)])
                if duplicate:
                    lead_owner_name = duplicate[0].lead_owner.name if duplicate[0].lead_owner else 'Unknown'
                    return {'warning': {'title': _("Duplicate Phone Number"), 'message': _(
                        "The phone number %s already exists in the system and is owned by %s.") % (
                        record.phone_number, lead_owner_name)}}

    @api.onchange('call_response')
    def _onchange_call_response(self):
        for record in self:
            if record.call_response:
                response_obj = self.env['call.responses'].search([('name', '=', record.call_response)], limit=1)
                if not response_obj:
                    response_obj = self.env['call.responses'].create({'name': record.call_response})
                record.call_responses = [(4, response_obj.id)]

    # ── Create ─────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get('reference_no', _('New')) == _('New'):
                values['reference_no'] = self.env['ir.sequence'].next_by_code('leads.logic') or _('New')
            if 'phone_number' in values:
                values['phone_number'] = values['phone_number'].replace(" ", "")
            if not values.get('lead_creator_id'):
                values['lead_creator_id'] = self.env.uid

            # ── Auto-compute quality from attendance % on create ──
            if 'attendance_percentage' in values:
                pct = values.get('attendance_percentage') or 0.0
                if pct > 75:
                    values['lead_quality'] = 'hot'
                elif pct > 50:
                    values['lead_quality'] = 'warm'
                elif pct > 30:
                    values['lead_quality'] = 'cold'
                else:
                    values['lead_quality'] = 'new'

        leads = super(LeadsForm, self).create(vals_list)
        # Backfill creator when created via sudo/API without explicit creator
        for lead, values in zip(leads, vals_list):
            if not lead.lead_creator_id and lead.create_uid:
                lead.lead_creator_id = lead.create_uid.id
        for lead in leads:
            if lead.lead_owner:
                self.env['lead.assignment.history'].create({
                    'lead_id': lead.id,
                    'owner_id': lead.lead_owner.id,
                    'assigned_date': fields.Datetime.now(),
                    'assigned_by': self.env.uid
                })
            if lead.tele_caller_id:
                notification_ids = [(0, 0, {'res_partner_id': lead.tele_caller_id.partner_id.id, 'notification_type': 'inbox'})]
                self.env['mail.message'].create({
                    'message_type': "notification",
                    'body': f"Lead '{lead.name}' has been assigned to you.",
                    'subject': "Lead Assigned",
                    'model': 'leads.logic',
                    'res_id': lead.id,
                    'partner_ids': [(4, lead.tele_caller_id.partner_id.id)],
                    'author_id': self.env.user.partner_id.id,
                    'notification_ids': notification_ids
                })
        return leads

    # ── Dashboard fast data fetch (single RPC) ────────────────────────────
    @api.model
    # ── Dashboard fast data fetch (single RPC) ────────────────────────────
    @api.model
    def get_dashboard_data(self):
        """
        Single RPC returning:
         - stage counts
         - team performance (ranked)
         - officer performance: admissions + processed leads (today/week/month/day-wise)
         - current user's own lead quality counts (today)
        """
        from datetime import date, timedelta
        import json

        user       = self.env.user
        is_manager = user.has_group('custom_leads_19.group_lead_manager')
        is_super   = user.has_group('custom_leads_19.group_super_admin')
        is_tl      = user.has_group('custom_leads_19.group_lead_team_lead')
        can_see    = is_manager or is_super or is_tl

        stage_keys = ['funnel','prospects','rnr_dnp','admission_done','re_try','alumni','junk']

        today       = date.today()
        week_start  = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        cr          = self.env.cr

        # Resolve the current user's employee record up-front — needed both
        # to scope stage_counts below (for non-elevated roles) and for the
        # "my quality counts" section further down.
        my_employee = self.env['hr.employee'].search(
            [('user_id','=',user.id)], limit=1
        )

        # ── 1. Overall stage counts ────────────────────────────────────────
        # Managers / Super Admins / Team Leads get the team-wide / org-wide
        # picture here (they already get the dedicated Team & Officer
        # leaderboard sections below for that). Everyone else (Admission
        # Officers, Tele Callers, etc.) only sees leads owned by THEM, so
        # these top cards stay consistent with "My Performance" instead of
        # showing the whole team's pipeline (which the ir.rule record rule
        # would otherwise expose to read_group).
        stage_domain = [('lead_stage_category', 'in', stage_keys)]
        if not can_see:
            stage_domain.append(('lead_owner', '=', my_employee.id if my_employee else False))

        rows = self.env['leads.logic'].read_group(
            domain=stage_domain,
            fields=['lead_stage_category'],
            groupby=['lead_stage_category'],
        )
        stage_counts = {r['lead_stage_category']: r['lead_stage_category_count'] for r in rows}

        # ── 2. Current user's own lead quality counts (today) ──────────────
        # "Touched today" = write_uid=user OR call log by user OR quality history by user, today
        my_quality_counts = {}
        if my_employee:
            quality_selections = [
                'new','hot','warm','cold','first_attempt',
                'waiting_for_admission','admission',
                'not_responding','call_later',
                'follow_up','not_reachable','not_attended',
                'already_joined',
                'wrong_number','not_interested',
            ]
            cr.execute("""
                SELECT ll.lead_quality, COUNT(DISTINCT ll.id)
                FROM leads_logic ll
                WHERE ll.lead_owner = %s
                  AND ll.lead_quality IS NOT NULL
                GROUP BY ll.lead_quality
            """, (my_employee.id,))
            my_quality_counts = {row[0]: row[1] for row in cr.fetchall()}

        # ── 3. "Processed" leads count per user per period ─────────────────
        # A lead is "processed" if the user touched it: write_uid match,
        # OR has a call log entry, OR has a quality history entry — in that period.
        def _processed_counts(emp_ids, user_ids, date_from, date_to):
            """
            Returns dict: user_id → count of distinct leads processed in period.
            Uses UNION of three touch sources.
            """
            if not user_ids:
                return {}
            uid_tuple = tuple(user_ids)
            if len(uid_tuple) == 1:
                uid_tuple = uid_tuple + uid_tuple   # avoid single-element tuple SQL issue
            cr.execute("""
                SELECT user_id, COUNT(DISTINCT lead_id) AS cnt
                FROM (
                    -- Touch 1: write_uid on the lead itself
                    SELECT write_uid AS user_id, id AS lead_id
                    FROM leads_logic
                    WHERE write_uid = ANY(%s::int[])
                      AND write_date >= %s AND write_date < %s

                    UNION

                    -- Touch 2: call log entry
                    SELECT cl.user_id, cl.lead_id
                    FROM lead_call_log cl
                    WHERE cl.user_id = ANY(%s::int[])
                      AND cl.call_time >= %s AND cl.call_time < %s

                    UNION

                    -- Touch 3: quality history entry
                    SELECT qh.user_id, qh.lead_id
                    FROM lead_quality_history qh
                    WHERE qh.user_id = ANY(%s::int[])
                      AND qh.change_date >= %s AND qh.change_date < %s
                ) t
                GROUP BY user_id
            """, (
                list(user_ids), str(date_from), str(date_to + timedelta(days=1)),
                list(user_ids), str(date_from), str(date_to + timedelta(days=1)),
                list(user_ids), str(date_from), str(date_to + timedelta(days=1)),
            ))
            return {row[0]: row[1] for row in cr.fetchall()}

        # ── 4. Day-wise processed for last 30 days (current user) ─────────
        my_daywise = []
        if my_employee and user.id:
            cr.execute("""
                SELECT day::date, COUNT(DISTINCT lead_id) AS cnt
                FROM (
                    SELECT DATE_TRUNC('day', write_date) AS day, id AS lead_id
                    FROM leads_logic
                    WHERE write_uid = %s
                      AND write_date >= %s

                    UNION

                    SELECT DATE_TRUNC('day', call_time) AS day, lead_id
                    FROM lead_call_log
                    WHERE user_id = %s
                      AND call_time >= %s

                    UNION

                    SELECT DATE_TRUNC('day', change_date) AS day, lead_id
                    FROM lead_quality_history
                    WHERE user_id = %s
                      AND change_date >= %s
                ) t
                GROUP BY day
                ORDER BY day
            """, (
                user.id, str(month_start),
                user.id, str(month_start),
                user.id, str(month_start),
            ))
            my_daywise = [{'date': str(row[0])[:10], 'count': row[1]} for row in cr.fetchall()]

        # ── 5. Teams + officer performance ────────────────────────────────
        team_data    = []
        officer_data = []

        if can_see:
            if is_manager or is_super:
                teams = self.env['lead.team'].search([('active','=',True)])
            else:
                teams = self.env['lead.team'].search([
                    ('team_lead_ids.user_id','=',user.id),
                    ('active','=',True),
                ])

            # Officers (team members)
            all_member_emp_ids = list(set(teams.mapped('member_ids.employee_id.id')))
            # Team Leads — include their leads in counts too
            tl_emp_ids = list(set(teams.mapped('team_lead_ids.id')))
            all_emp_ids_for_counts = list(set(all_member_emp_ids + tl_emp_ids))
            all_user_ids = list(set(
                self.env['hr.employee'].browse(all_emp_ids_for_counts).mapped('user_id.id')
            ))
            all_user_ids = [u for u in all_user_ids if u]

            # Admission counts — 4 read_groups
            def _rg_adm(extra_domain):
                dom = [('lead_stage_category','=','admission_done'),
                       ('lead_owner','!=',False)]
                if all_emp_ids_for_counts:
                    dom += [('lead_owner','in',all_emp_ids_for_counts)]
                else:
                    return {}
                dom += extra_domain
                return {
                    r['lead_owner'][0]: r['lead_owner_count']
                    for r in self.env['leads.logic'].read_group(
                        domain=dom, fields=['lead_owner'], groupby=['lead_owner'],
                    )
                }

            adm_today = _rg_adm([('admission_date','>=',str(today)),
                                  ('admission_date','<', str(today+timedelta(days=1)))])
            adm_week  = _rg_adm([('admission_date','>=',str(week_start))])
            adm_month = _rg_adm([('admission_date','>=',str(month_start))])
            adm_total = _rg_adm([])

            # Processed counts per period
            proc_today = _processed_counts(all_member_emp_ids, all_user_ids, today, today)
            proc_week  = _processed_counts(all_member_emp_ids, all_user_ids, week_start, today)
            proc_month = _processed_counts(all_member_emp_ids, all_user_ids, month_start, today)

            emp_records = self.env['hr.employee'].browse(all_member_emp_ids)
            emp_name    = {e.id: e.name for e in emp_records}
            emp_user    = {e.id: e.user_id.id for e in emp_records}

            for team in teams:
                t_rows = self.env['leads.logic'].read_group(
                    domain=[('team_id','=',team.id),
                            ('lead_stage_category','in',stage_keys)],
                    fields=['lead_stage_category'],
                    groupby=['lead_stage_category'],
                )
                t_counts   = {r['lead_stage_category']: r['lead_stage_category_count'] for r in t_rows}
                total      = sum(t_counts.values())
                admissions = t_counts.get('admission_done', 0)

                team_officers = []

                # ── Team Leads first ────────────────────────────────────
                for tl_emp in team.team_lead_ids:
                    eid = tl_emp.id
                    uid = tl_emp.user_id.id if tl_emp.user_id else None
                    o = {
                        'id':         eid,
                        'name':       tl_emp.name + ' (TL)',
                        'tl':         tl_emp.name,
                        'team':       team.name,
                        'is_tl':      True,
                        'adm_today':  adm_today.get(eid, 0),
                        'adm_week':   adm_week.get(eid, 0),
                        'adm_month':  adm_month.get(eid, 0),
                        'adm_total':  adm_total.get(eid, 0),
                        'proc_today': proc_today.get(uid, 0) if uid else 0,
                        'proc_week':  proc_week.get(uid, 0)  if uid else 0,
                        'proc_month': proc_month.get(uid, 0) if uid else 0,
                    }
                    team_officers.append(o)
                    officer_data.append(o)

                # ── Officers (members) ──────────────────────────────────
                for member in team.member_ids:
                    eid  = member.employee_id.id
                    uid  = emp_user.get(eid)
                    o = {
                        'id':            eid,
                        'name':          emp_name.get(eid, member.employee_id.name),
                        'tl':            member.team_lead_id.name if member.team_lead_id else '',
                        'team':          team.name,
                        'is_tl':         False,
                        'adm_today':     adm_today.get(eid, 0),
                        'adm_week':      adm_week.get(eid, 0),
                        'adm_month':     adm_month.get(eid, 0),
                        'adm_total':     adm_total.get(eid, 0),
                        'proc_today':    proc_today.get(uid, 0) if uid else 0,
                        'proc_week':     proc_week.get(uid, 0)  if uid else 0,
                        'proc_month':    proc_month.get(uid, 0) if uid else 0,
                    }
                    team_officers.append(o)
                    officer_data.append(o)

                team_officers.sort(key=lambda x: x['adm_month'], reverse=True)
                for i, o in enumerate(team_officers):
                    o['rank'] = i + 1

                team_data.append({
                    'id':           team.id,
                    'name':         team.name,
                    'total':        total,
                    'admissions':   admissions,
                    'prospects':    t_counts.get('prospects',0),
                    'funnel':       t_counts.get('funnel',0),
                    'rnr_dnp':      t_counts.get('rnr_dnp',0),
                    're_try':       t_counts.get('re_try',0),
                    'junk':         t_counts.get('junk',0),
                    'conversion':   round((admissions/total*100),1) if total else 0,
                    'team_leads':   [tl.name for tl in team.team_lead_ids],
                    'member_count': len(team.member_ids),
                    'officers':     team_officers,
                })

            team_data.sort(key=lambda t: t['admissions'], reverse=True)
            for i, t in enumerate(team_data):
                t['rank'] = i + 1

            seen = {}
            for o in officer_data:
                eid = o['id']
                if eid not in seen or o['adm_month'] > seen[eid]['adm_month']:
                    seen[eid] = o
            officer_data = sorted(seen.values(), key=lambda o: o['adm_month'], reverse=True)
            for i, o in enumerate(officer_data):
                o['rank'] = i + 1

        return {
            'stage_counts':      stage_counts,
            'can_see_teams':     can_see,
            'is_manager':        is_manager or is_super,
            'team_data':         team_data,
            'officer_data':      officer_data,
            'my_quality_counts': my_quality_counts,
            'my_daywise':        my_daywise,
            'today_str':         str(today),
        }

    def _auto_init(self):
        res = super()._auto_init()
        self.env.cr.execute("""
            UPDATE leads_logic
               SET lead_creator_id = create_uid
             WHERE lead_creator_id IS NULL
               AND create_uid IS NOT NULL
        """)
        # Recompute team_id for leads owned by team leads (previously missed).
        # Guard: lead_team table may not exist yet on a fresh install
        # (other models' _auto_init may not have run yet), so check first.
        self.env.cr.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                 WHERE table_schema = 'public'
                   AND table_name = 'lead_team'
            )
        """)
        if self.env.cr.fetchone()[0]:
            self.env.cr.execute("""
                UPDATE leads_logic ll
                   SET team_id = lt.id
                  FROM lead_team lt
                  JOIN lead_team_teamlead_rel ltlr ON ltlr.team_id = lt.id
                 WHERE ll.lead_owner = ltlr.employee_id
                   AND ll.team_id IS NULL
                   AND ll.lead_owner IS NOT NULL
            """)
        return res

    # ── Export Audit ───────────────────────────────────────────────────────
    def export_data(self, fields_to_export):
        ip_addr = 'Unknown'
        if request:
            ip_addr = request.httprequest.remote_addr
        self.env['lead.export.history'].sudo().create({
            'user_id': self.env.user.id,
            'export_date': fields.Datetime.now(),
            'record_count': len(self),
            'exported_fields': ", ".join(fields_to_export),
            'ip_address': ip_addr,
        })
        for record in self:
            record.message_post(body=f"⚠️ This lead was exported by {self.env.user.name} on {fields.Datetime.now()}")
        return super(LeadsForm, self).export_data(fields_to_export)


# --------------------------------------------------------------------------
# Model: call.responses
# --------------------------------------------------------------------------
class CallResponses(models.Model):
    _name = "call.responses"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Text(string="Call Responses")


# --------------------------------------------------------------------------
# Model: lead.response
# --------------------------------------------------------------------------
class LeadResponse(models.Model):
    _name = 'lead.response'
    _description = 'Lead Comments / Responses'
    _rec_name = 'comment'
    _order = 'response_time desc'

    lead_id = fields.Many2one('leads.logic', string="Lead", ondelete='cascade')
    user_id = fields.Many2one('res.users', string="Responded By", default=lambda self: self.env.user)
    comment = fields.Text(string="Response / Comment", required=True)
    response_time = fields.Datetime(string="Response Time", default=fields.Datetime.now)
    is_editable = fields.Boolean(string="Editable", default=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(LeadResponse, self).create(vals_list)
        for record in records:
            if record.lead_id and record.comment:
                safe_comment = html_escape(record.comment)
                message = Markup(
                    "<div><strong>💬 New Response Added</strong><br/>"
                    "<strong>By:</strong> %s<br/>"
                    "<strong>Comment:</strong> %s</div>"
                ) % (record.user_id.name, safe_comment)
                record.lead_id.message_post(body=message, subtype_xmlid="mail.mt_note")
        return records

    def action_enable_edit(self):
        for rec in self:
            rec.is_editable = True

    def name_get(self):
        result = []
        for record in self:
            user = record.user_id.name or "Unknown"
            date_str = record.response_time.strftime("%d-%b %H:%M") if record.response_time else ""
            comment_preview = (record.comment[:25] + '...') if record.comment and len(record.comment) > 25 else (record.comment or "")
            result.append((record.id, f"{user} – {comment_preview} ({date_str})"))
        return result


# --------------------------------------------------------------------------
# Model: course.interested
# --------------------------------------------------------------------------
class CourseInterested(models.Model):
    _name = "course.interested"

    name = fields.Char(string="Course Name")


# --------------------------------------------------------------------------
# Model: lead.call.log
# --------------------------------------------------------------------------
class LeadCallLog(models.Model):
    _name = "lead.call.log"
    _description = "Lead Call Log"
    _order = "call_time desc"

    lead_id = fields.Many2one("leads.logic", string="Lead", ondelete="cascade")
    user_id = fields.Many2one("res.users", string="Agent", default=lambda self: self.env.user)
    call_time = fields.Datetime(string="Call Time", default=lambda self: fields.Datetime.now())
    remarks = fields.Text(string="Remarks")
    call_uuid = fields.Char(string="Call UUID")
    caller_number = fields.Char(string="Caller Number")
    call_status = fields.Char(string="Call Status")
    duration = fields.Char(string="Duration")
    recording_url = fields.Char(string="Recording URL")
    call_type = fields.Selection([('incoming', 'Incoming'), ('outgoing', 'Outgoing')], string="Call Type")

    # ── Recording attachment ──────────────────────────────────────────────────
    recording = fields.Binary(string="Recording File", attachment=True)
    recording_filename = fields.Char(string="Recording Filename")
    recording_mimetype = fields.Char(string="Recording MIME Type")
    has_recording = fields.Boolean(string="Has Recording", compute='_compute_has_recording', store=True)

    @api.depends('recording', 'recording_url')
    def _compute_has_recording(self):
        for rec in self:
            rec.has_recording = bool(rec.recording or rec.recording_url)

    def action_save_recording(self, base64_data, filename, mimetype='audio/webm'):
        """Called from JS to save a browser-recorded audio file."""
        self.ensure_one()
        self.write({
            'recording': base64_data,
            'recording_filename': filename,
            'recording_mimetype': mimetype,
        })
        return True

    def action_upload_recording(self):
        """Open file upload dialog for manual recording upload."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '📎 Upload Call Recording',
            'res_model': 'call.recording.upload.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_call_log_id': self.id},
        }


# --------------------------------------------------------------------------
# Model: lead.followup
# --------------------------------------------------------------------------
class LeadFollowUp(models.Model):
    _name = "lead.followup"
    _description = "Lead Follow-Up"
    _rec_name = "display_name"
    _order = 'status desc, next_followup_date asc'

    display_name = fields.Char(compute='_compute_display_name', store=True)
    lead_id = fields.Many2one('leads.logic', string="Lead", ondelete="cascade", required=True)
    lead_reference = fields.Char(related='lead_id.reference_no', string='Lead Reference', readonly=True)
    lead_owner_id = fields.Many2one(related='lead_id.lead_owner', string='Lead Owner', readonly=True)
    user_id = fields.Many2one('res.users', string="Follow-Up By", default=lambda self: self.env.user)
    next_followup_date = fields.Datetime(string="Next Follow-Up Date", required=True)
    remarks = fields.Text(string="Remarks")
    phone_number = fields.Char(string="Phone Number")
    status = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string="Status", default='scheduled')

    @api.depends('lead_id.name', 'next_followup_date', 'status')
    def _compute_display_name(self):
        for rec in self:
            parts = []
            if rec.lead_id:
                parts.append(rec.lead_id.name)
            if rec.next_followup_date:
                parts.append(rec.next_followup_date.strftime('%d %b %Y %H:%M'))
            rec.display_name = ' – '.join(parts) if parts else _('Follow-Up')

    def action_open_lead(self):
        self.ensure_one()
        if not self.lead_id:
            raise UserError(_("No lead linked to this follow-up."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lead'),
            'res_model': 'leads.logic',
            'view_mode': 'form',
            'res_id': self.lead_id.id,
            'target': 'current',
        }

    @api.model
    def action_view_today_followups(self):
        followup_ids = [row['id'] for row in self.get_today_followups()]
        return {
            'type': 'ir.actions.act_window',
            'name': _("Today's Follow-Ups"),
            'res_model': 'lead.followup',
            'view_mode': 'list,form',
            'domain': [('id', 'in', followup_ids)] if followup_ids else [('id', '=', 0)],
            'search_view_id': self.env.ref('custom_leads_19.view_lead_followup_search').id,
            'context': {'search_default_scheduled': 1},
        }

    @api.model
    def get_today_followups(self):
        """Return today's scheduled follow-ups for the popup (user timezone)."""
        today = fields.Date.context_today(self)
        candidates = self.search([
            ('status', '=', 'scheduled'),
            ('next_followup_date', '!=', False),
        ], order='next_followup_date asc', limit=200)
        result = []
        for followup in candidates:
            local_dt = fields.Datetime.context_timestamp(self, followup.next_followup_date)
            if local_dt.date() != today:
                continue
            lead = followup.lead_id
            result.append({
                'id': followup.id,
                'lead_id': lead.id,
                'lead_name': lead.display_name or lead.name or _('Unknown Lead'),
                'next_followup_date': fields.Datetime.to_string(followup.next_followup_date),
                'remarks': followup.remarks or '',
                'phone_number': followup.phone_number or lead.phone_number or '',
            })
            if len(result) >= 100:
                break
        return result

    @api.model
    def _cron_remind_upcoming_followups(self):
        now = fields.Datetime.now()
        upcoming = now + timedelta(hours=1)
        followups = self.search([('next_followup_date', '>=', now), ('next_followup_date', '<=', upcoming), ('status', '=', 'scheduled')])
        for followup in followups:
            if followup.lead_id:
                followup.lead_id.message_post(
                    body=f"🔔 Reminder: Follow-up due on {followup.next_followup_date.strftime('%d %b %Y %H:%M')} for {followup.user_id.name}.")
                self.env['mail.activity'].create({
                    'res_model': 'leads.logic', 'res_id': followup.lead_id.id, 'user_id': followup.user_id.id,
                    'summary': 'Follow-Up Reminder',
                    'note': f'Upcoming follow-up at {followup.next_followup_date.strftime("%d %b %Y %H:%M")}',
                    'date_deadline': followup.next_followup_date.date(),
                })

    def action_mark_done(self):
        for record in self:
            record.status = 'done'
            if record.lead_id:
                record.lead_id.message_post(
                    body=f"✅ Follow-up marked as Done by {self.env.user.name} (Scheduled: {record.next_followup_date.strftime('%d %b %Y %H:%M')})")


# --------------------------------------------------------------------------
# Model: lead.followup.wizard
# --------------------------------------------------------------------------
class LeadFollowUpWizard(models.TransientModel):
    _name = "lead.followup.wizard"
    _description = "Add Follow-Up Wizard"

    lead_name = fields.Char(string='Lead', compute='_compute_lead_name', readonly=True)
    next_followup_date = fields.Datetime(string="Next Follow-Up Date", required=True)
    remarks = fields.Text(string="Remarks")

    def _get_lead_id_from_context(self):
        return self.env.context.get('default_lead_id') or self.env.context.get('active_id')

    @api.depends_context('default_lead_id', 'active_id')
    def _compute_lead_name(self):
        for wizard in self:
            lead_id = wizard._get_lead_id_from_context()
            if lead_id:
                wizard.lead_name = self.env['leads.logic'].browse(lead_id).name
            else:
                wizard.lead_name = ''

    def action_save_followup(self):
        self.ensure_one()
        lead_id = self._get_lead_id_from_context()
        if not lead_id:
            raise UserError(_("Lead is missing."))
        lead = self.env['leads.logic'].browse(lead_id)
        if not lead.exists():
            raise UserError(_("Lead not found."))
        self.env['lead.followup'].create({
            'lead_id': lead.id,
            'user_id': self.env.user.id,
            'next_followup_date': self.next_followup_date,
            'remarks': self.remarks,
            'phone_number': lead.phone_number,
            'status': 'scheduled',
        })
        lead.write({'next_follow_up_date': self.next_followup_date.date()})
        lead.message_post(body=_(
            "📞 Follow-up scheduled on %(date)s by %(user)s<br/>%(remarks)s"
        ) % {
            'date': self.next_followup_date.strftime('%d %b %Y %H:%M'),
            'user': self.env.user.name,
            'remarks': self.remarks or '',
        })
        return {'type': 'ir.actions.act_window_close'}


# --------------------------------------------------------------------------
# Model: course.fee.structure
# --------------------------------------------------------------------------
class CourseFeeStructure(models.Model):
    _name = 'course.fee.structure'
    _description = 'Course Fee Structure'

    course_name = fields.Char(string="Course Name")
    level = fields.Char(string="Level")
    duration = fields.Char(string="Duration")
    amount = fields.Float(string="Fees (INR)")
    image = fields.Binary(string="Course Image", attachment=True)


# --------------------------------------------------------------------------
# Model: lead.unlock.wizard
# --------------------------------------------------------------------------
class LeadUnlockWizard(models.TransientModel):
    _name = "lead.unlock.wizard"
    _description = "Unlock Lead Editing Wizard"

    lead_id = fields.Many2one("leads.logic", required=True)

    def action_unlock(self):
        self.lead_id.is_editable = True
        return {'type': 'ir.actions.act_window_close'}


# --------------------------------------------------------------------------
# Model: webinar.invite.wizard
# --------------------------------------------------------------------------
class WebinarInviteWizard(models.TransientModel):
    _name = 'webinar.invite.wizard'
    _description = 'Webinar Invite Wizard'

    lead_id = fields.Many2one('leads.logic', required=True)
    zoom_link = fields.Char(string='Zoom Link', required=True)
    webinar_date = fields.Char(string='Webinar Date / Time')

    def action_send_whatsapp(self):
        self.ensure_one()
        phone = self.lead_id.phone_number
        if not phone:
            return {'type': 'ir.actions.act_window_close'}
        message = (
            f"Hi {self.lead_id.name or ''},\n\n"
            "You are invited to our Free Webinar.\n\n"
            f"Date & Time: {self.webinar_date or 'Will be shared shortly'}\n"
            f"Zoom Link: {self.zoom_link}\n\n"
            "Please join on time."
        )
        self.lead_id.write({
            'webinar_invite_sent': True, 'webinar_invite_sent_on': fields.Datetime.now(),
            'webinar_invite_sent_by': self.env.user.id, 'webinar_zoom_link': self.zoom_link
        })
        whatsapp_url = 'https://wa.me/%s?text=%s' % (phone.replace('+', '').replace(' ', ''), quote(message))
        return {'type': 'ir.actions.act_url', 'url': whatsapp_url, 'target': 'new'}


# --------------------------------------------------------------------------
# Model: lead.open.history
# --------------------------------------------------------------------------
class LeadOpenHistory(models.Model):
    _name = 'lead.open.history'
    _description = 'Lead Open History'
    _order = 'opened_on desc'

    lead_id = fields.Many2one('leads.logic', string='Lead', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string='Opened By', required=True)
    opened_on = fields.Datetime(string='Opened On', default=fields.Datetime.now)
    ip_address = fields.Char(string='IP Address')
    remarks = fields.Char(string='Remarks')


# --------------------------------------------------------------------------
# Model: lead.export.history
# --------------------------------------------------------------------------
class LeadExportHistory(models.Model):
    _name = 'lead.export.history'
    _description = 'Lead Export Audit'
    _order = 'export_date desc'

    user_id = fields.Many2one('res.users', string='Exported By', default=lambda self: self.env.user)
    export_date = fields.Datetime(string='Export Date', default=fields.Datetime.now)
    record_count = fields.Integer(string='Number of Records')
    exported_fields = fields.Text(string='Fields Exported')
    ip_address = fields.Char(string='IP Address')
