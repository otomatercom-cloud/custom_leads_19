# -*- coding: utf-8 -*-
"""Hiring process on a hiring lead: stages (request resume -> interview -> selected/rejected), the applicant details
collected by the public form, the resume, and the interview schedule."""
import re
from urllib.parse import quote
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError

HIRING_STAGES = [
    ('new', 'New applicant'), ('resume_requested', 'Resume requested'), ('resume_received', 'Resume received'),
    ('interview_scheduled', 'Interview scheduled'), ('interviewed', 'Interviewed'),
    ('selected', 'Selected'), ('rejected', 'Rejected'),
]
INTERVIEW_MODES = [('office', 'At office'), ('online', 'Online / video'), ('phone', 'Phone')]


class LeadsLogicHiringProcess(models.Model):
    _inherit = 'leads.logic'

    hiring_stage = fields.Selection(HIRING_STAGES, string='Hiring stage', default='new', tracking=True, copy=False)
    hiring_form_token = fields.Char(copy=False, index=True)
    hiring_form_url = fields.Char(string='Application form link', compute='_compute_hiring_form_url')
    hiring_form_submitted_on = fields.Datetime(string='Form submitted on', copy=False, readonly=True)
    hiring_position = fields.Char(string='Position applied for')
    hiring_qualification = fields.Char(string='Highest qualification')
    hiring_experience = fields.Float(string='Experience (years)')
    hiring_current_company = fields.Char(string='Current / last company')
    hiring_current_salary = fields.Char(string='Current salary')
    hiring_expected_salary = fields.Char(string='Expected salary')
    hiring_notice_period = fields.Char(string='Notice period')
    hiring_email = fields.Char(string='Applicant email')
    hiring_skills = fields.Text(string='Skills / about the applicant')
    hiring_resume = fields.Binary(string='Resume', attachment=True, copy=False)
    hiring_resume_filename = fields.Char(string='Resume file name', copy=False)
    interview_dt = fields.Datetime(string='Interview date and time', tracking=True, copy=False)
    interview_mode = fields.Selection(INTERVIEW_MODES, string='Interview mode', copy=False)
    interview_with = fields.Char(string='Interviewer', copy=False)
    interview_note = fields.Text(string='Interview place / link / note', copy=False)

    @api.depends('hiring_form_token')
    def _compute_hiring_form_url(self):
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        for lead in self:
            lead.hiring_form_url = '%s/hiring/apply/%s' % (base, lead.hiring_form_token) if lead.hiring_form_token else False

    # ── helpers ────────────────────────────────────────────────────────
    def _hiring_wa_url(self, text):
        self.ensure_one()
        phone = re.sub(r'\D', '', self.phone_number or '')
        if len(phone) == 10:
            phone = '91' + phone
        if not phone:
            raise UserError(_('This lead has no mobile number.'))
        return 'https://wa.me/%s?text=%s' % (phone, quote(text))

    def _hiring_open_wa(self, text):
        return {'type': 'ir.actions.act_url', 'url': self._hiring_wa_url(text), 'target': 'new'}

    def _hiring_check(self):
        for lead in self:
            if not lead.is_hiring:
                raise UserError(_('This is not a hiring lead.'))

    # ── buttons ────────────────────────────────────────────────────────
    def action_hiring_request_resume(self):
        """Create the applicant's form link and open WhatsApp with the message ready to send."""
        self.ensure_one()
        self._hiring_check()
        if not self.hiring_form_token:
            self.sudo().hiring_form_token = secrets.token_urlsafe(16)
        if self.hiring_stage == 'new':
            self.hiring_stage = 'resume_requested'
        self.message_post(body=_('Application form link sent to the applicant: %s') % self.hiring_form_url)
        text = _('Hello %(name)s, thank you for your interest in working with %(company)s. '
                 'Please fill in your details and upload your resume here: %(url)s') % {
            'name': self.name or '', 'company': self.env.company.name, 'url': self.hiring_form_url}
        return self._hiring_open_wa(text)

    def action_hiring_schedule_interview(self):
        self.ensure_one()
        self._hiring_check()
        return {
            'type': 'ir.actions.act_window', 'name': _('Schedule interview'), 'res_model': 'leads.hiring.interview.wizard',
            'view_mode': 'form', 'target': 'new', 'context': {'default_lead_id': self.id}}

    def action_hiring_send_interview_details(self):
        self.ensure_one()
        if not self.interview_dt:
            raise UserError(_('Schedule the interview first.'))
        when = fields.Datetime.context_timestamp(self, self.interview_dt).strftime('%d %b %Y, %I:%M %p')
        mode = dict(INTERVIEW_MODES).get(self.interview_mode, '')
        text = _('Hello %(name)s, your interview with %(company)s is scheduled on %(when)s (%(mode)s).%(note)s '
                 'Please reply to confirm.') % {
            'name': self.name or '', 'company': self.env.company.name, 'when': when, 'mode': mode,
            'note': (' ' + self.interview_note) if self.interview_note else ''}
        return self._hiring_open_wa(text)

    def _hiring_set_stage(self, stage, note):
        self._hiring_check()
        for lead in self:
            lead.hiring_stage = stage
            lead.message_post(body=note)
        return True

    def action_hiring_interviewed(self):
        return self._hiring_set_stage('interviewed', _('Interview completed.'))

    def action_hiring_select(self):
        return self._hiring_set_stage('selected', _('Applicant selected.'))

    def action_hiring_reject(self):
        return self._hiring_set_stage('rejected', _('Applicant rejected.'))


class LeadsHiringInterviewWizard(models.TransientModel):
    _name = 'leads.hiring.interview.wizard'
    _description = 'Schedule interview'

    lead_id = fields.Many2one('leads.logic', required=True, ondelete='cascade')
    interview_dt = fields.Datetime(string='Date and time', required=True)
    interview_mode = fields.Selection(INTERVIEW_MODES, string='Mode', required=True, default='office')
    interview_with = fields.Char(string='Interviewer')
    interview_note = fields.Text(string='Place / meeting link / note')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        lead = self.env['leads.logic'].browse(res.get('lead_id') or self.env.context.get('default_lead_id'))
        if lead:
            res.update({'interview_dt': lead.interview_dt, 'interview_mode': lead.interview_mode or 'office',
                        'interview_with': lead.interview_with, 'interview_note': lead.interview_note})
        return res

    def action_confirm(self):
        self.ensure_one()
        lead = self.lead_id
        lead.write({'interview_dt': self.interview_dt, 'interview_mode': self.interview_mode,
                    'interview_with': self.interview_with, 'interview_note': self.interview_note,
                    'hiring_stage': 'interview_scheduled'})
        when = fields.Datetime.context_timestamp(lead, self.interview_dt).strftime('%d %b %Y, %I:%M %p')
        lead.message_post(body=_('Interview scheduled for %s.') % when)
        # a follow-up at the interview time so the usual reminder popup fires
        self.env['lead.followup'].sudo().create({
            'lead_id': lead.id, 'user_id': self.env.uid, 'next_followup_date': self.interview_dt,
            'remarks': _('Interview'), 'phone_number': lead.phone_number})
        return {'type': 'ir.actions.act_window_close'}
