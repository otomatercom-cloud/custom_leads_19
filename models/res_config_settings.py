from odoo import models, fields, api

PARAM_FOLLOWUP = 'custom_leads_19.enable_followup_popup'
PARAM_CALL_TIMER = 'custom_leads_19.enable_call_timer'
PARAM_BATCH_REQUIRED = 'custom_leads_19.admission_batch_required'
PARAM_BATCH_REQUIRED = 'custom_leads_19.admission_batch_required'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    voxbay_uid = fields.Char(related='company_id.voxbay_uid', string='Voxbay UID', readonly=False)
    voxbay_upin = fields.Char(related='company_id.voxbay_upin', string='Voxbay UPIN', readonly=False)
    voxbay_callerid = fields.Char(related='company_id.voxbay_callerid', string='Voxbay Caller ID (DID)', readonly=False)

    bonvoice_username = fields.Char(related='company_id.bonvoice_username', string='Bonvoice Username', readonly=False)
    bonvoice_password = fields.Char(related='company_id.bonvoice_password', string='Bonvoice Password', readonly=False)
    bonvoice_leg_a_caller_id = fields.Char(related='company_id.bonvoice_leg_a_caller_id', string='Bonvoice Leg A Caller ID', readonly=False)
    bonvoice_leg_b_caller_id = fields.Char(related='company_id.bonvoice_leg_b_caller_id', string='Bonvoice Leg B Caller ID', readonly=False)
    bonvoice_url = fields.Char(related='company_id.bonvoice_url', string='Bonvoice Auto Call API URL', readonly=False)

    meta_verify_token = fields.Char(related='company_id.meta_verify_token', string='Meta Verify Token', readonly=False)
    meta_page_access_token = fields.Char(related='company_id.meta_page_access_token', string='Meta Page Access Token', readonly=False)

    # ── Toggles: compute/inverse pattern — works in Odoo 19 ──────────────────

    enable_followup_popup = fields.Boolean(
        string='Enable Follow-Up Popup',
        help="When enabled, a popup shows today's follow-ups when opening the Leads form/list view.",
        compute='_compute_enable_followup_popup',
        inverse='_inverse_enable_followup_popup',
    )

    admission_batch_required = fields.Boolean(
        string='Require Batch & Fee Selection for Admission',
        help='Enable to force officers to select batch and fee structure. '
             'Disable for one-click admission (no batch/fee required).',
        config_parameter='custom_leads_19.admission_batch_required',
    )

    enable_call_timer = fields.Boolean(
        string='Enable Call Timer Popup',
        help="When ON: clicking Call opens the timer overlay with duration tracking and recording. "
             "When OFF: clicking Call directly dials via tel: link with no overlay.",
        compute='_compute_enable_call_timer',
        inverse='_inverse_enable_call_timer',
    )

    @api.depends_context('company')
    def _compute_enable_followup_popup(self):
        val = self.env['ir.config_parameter'].sudo().get_param(PARAM_FOLLOWUP)
        # Default True when never set; False only when explicitly set to '0'
        enabled = (val != '0')
        for rec in self:
            rec.enable_followup_popup = enabled

    def _inverse_enable_followup_popup(self):
        for rec in self:
            self.env['ir.config_parameter'].sudo().set_param(
                PARAM_FOLLOWUP, '1' if rec.enable_followup_popup else '0'
            )

    @api.depends_context('company')
    def _compute_enable_call_timer(self):
        val = self.env['ir.config_parameter'].sudo().get_param(PARAM_CALL_TIMER)
        enabled = (val != '0')
        for rec in self:
            rec.enable_call_timer = enabled

    def _inverse_enable_call_timer(self):
        for rec in self:
            self.env['ir.config_parameter'].sudo().set_param(
                PARAM_CALL_TIMER, '1' if rec.enable_call_timer else '0'
            )


class LeadsConfigHelper(models.AbstractModel):
    """Lightweight helper model for JS RPC calls."""
    _name = 'leads.config.helper'
    _description = 'Leads Config Helper'

    @api.model
    def get_followup_popup_enabled(self):
        val = self.env['ir.config_parameter'].sudo().get_param(PARAM_FOLLOWUP)
        return val != '0'

    @api.model
    def get_call_timer_enabled(self):
        val = self.env['ir.config_parameter'].sudo().get_param(PARAM_CALL_TIMER)
        return val != '0'

    @api.model
    def get_admission_batch_required(self):
        val = self.env['ir.config_parameter'].sudo().get_param(PARAM_BATCH_REQUIRED)
        return val == '1'
