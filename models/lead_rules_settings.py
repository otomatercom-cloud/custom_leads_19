# -*- coding: utf-8 -*-
"""One place (Settings > Leads > Lead rules) for numbers that used to live in code."""
from odoo import api, fields, models

P_FAST = 'custom_leads_19.called_fast_hrs'
P_SHORT = 'custom_leads_19.short_call_secs'
P_RNR = 'custom_leads_19.rnr_min_calls'
P_PASS = 'custom_leads_19.coaching_pass_score'
P_RNR_GAP = 'custom_leads_19.rnr_call_gap_min'
DEFAULTS = {P_FAST: 1.0, P_SHORT: 30, P_RNR: 3, P_PASS: 70, P_RNR_GAP: 150}


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
    lead_rnr_gap_min = fields.Integer(
        string='Minimum gap between RNR calls (minutes)', config_parameter=P_RNR_GAP, default=DEFAULTS[P_RNR_GAP],
        help='Only calls at least this far apart count towards Ringing Not Responding (150 = 2 h 30 min). '
             'After this gap with no answer the officer gets an "RNR call not done" popup. 0 = no gap rule.')
    coaching_pass_score = fields.Integer(
        string='Coaching pass score (%)', config_parameter=P_PASS, default=DEFAULTS[P_PASS],
        help='Officers whose average call review score is below this show as "Needs help".')

    score_w_fresh = fields.Integer(string='Priority: new lead', config_parameter='custom_leads_19.score_w_fresh',
                                   default=15, help='Points (of 100) for how recently the lead arrived.')
    score_w_calls = fields.Integer(string='Priority: not called yet', config_parameter='custom_leads_19.score_w_calls',
                                   default=10, help='Full points for a lead with no calls, fewer with every call.')
    score_w_source = fields.Integer(string='Priority: lead source', config_parameter='custom_leads_19.score_w_source',
                                    default=8, help='Points for sources that turn into admissions most often.')
    score_w_course = fields.Integer(string='Priority: course', config_parameter='custom_leads_19.score_w_course',
                                    default=4, help='Points for courses that turn into admissions most often.')
    score_w_due = fields.Integer(string='Priority: follow-up due', config_parameter='custom_leads_19.score_w_due',
                                 default=3, help='Points when a follow-up is due today or overdue.')


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
