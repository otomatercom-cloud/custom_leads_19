# -*- coding: utf-8 -*-
"""One place (Settings > Leads > Lead rules) for numbers that used to live in code."""
from odoo import api, fields, models

P_FAST = 'custom_leads_19.called_fast_hrs'
P_SHORT = 'custom_leads_19.short_call_secs'
P_RNR = 'custom_leads_19.rnr_min_calls'
P_PASS = 'custom_leads_19.coaching_pass_score'
DEFAULTS = {P_FAST: 1.0, P_SHORT: 30, P_RNR: 3, P_PASS: 70}


class ResConfigSettingsLeadRules(models.TransientModel):
    _inherit = 'res.config.settings'

    lead_called_fast_hrs = fields.Float(
        string='Called fast within (hours)', config_parameter=P_FAST, default=DEFAULTS[P_FAST],
        help='A lead counts as "called fast" when the first call is made within this many hours.')
    lead_short_call_secs = fields.Integer(
        string='Short call is under (seconds)', config_parameter=P_SHORT, default=DEFAULTS[P_SHORT],
        help='Connected calls shorter than this appear in the "Short calls" report.')
    lead_rnr_min_calls = fields.Integer(
        string='Calls needed before Ringing Not Responding', config_parameter=P_RNR,
        default=DEFAULTS[P_RNR],
        help='A lead cannot be set to Ringing Not Responding until it has this many calls. 0 = no limit.')
    coaching_pass_score = fields.Integer(
        string='Coaching pass score (%)', config_parameter=P_PASS, default=DEFAULTS[P_PASS],
        help='Officers whose average call review score is below this show as "Needs help".')


class LeadsLogicRuleParams(models.AbstractModel):
    _name = 'otm.lead.rule.params'
    _description = 'Lead rule settings reader'

    @api.model
    def param(self, param):
        raw = self.env['ir.config_parameter'].sudo().get_param(param)
        default = DEFAULTS[param]
        if raw in (None, False, ''):
            return default
        try:
            return float(raw) if isinstance(default, float) else int(float(raw))
        except (TypeError, ValueError):
            return default
