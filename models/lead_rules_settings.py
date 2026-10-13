# -*- coding: utf-8 -*-
"""One place (Settings > Leads > Lead rules) for numbers that used to live in code."""
from odoo import api, fields, models

P_FAST = 'custom_leads_19.called_fast_hrs'
P_SHORT = 'custom_leads_19.short_call_secs'
P_RNR = 'custom_leads_19.rnr_min_calls'
P_PASS = 'custom_leads_19.coaching_pass_score'
P_RNR_GAP = 'custom_leads_19.rnr_call_gap_min'
P_GAP_NOON = 'custom_leads_19.rnr_gap_noon_min'
P_GAP_EVE = 'custom_leads_19.rnr_gap_eve_min'
P_NOON_H = 'custom_leads_19.rnr_noon_hour'
P_EVE_H = 'custom_leads_19.rnr_eve_hour'
P_DAY_START = 'custom_leads_19.rnr_day_start'
P_DAY_END = 'custom_leads_19.rnr_day_end'
P_GENUINE = 'custom_leads_19.rnr_genuine_gap_min'
P_GAP_TOL = 'custom_leads_19.rnr_gap_tolerance_min'
DEFAULTS = {P_FAST: 1.0, P_SHORT: 30, P_RNR: 3, P_PASS: 70, P_RNR_GAP: 150,
            P_GAP_NOON: 90, P_GAP_EVE: 30, P_NOON_H: 12, P_EVE_H: 16, P_GAP_TOL: 15, P_DAY_START: 10.75, P_DAY_END: 19.0, P_GENUINE: 30}


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
        string='Gap between RNR calls - lead came in the morning (minutes)', config_parameter=P_RNR_GAP,
        default=DEFAULTS[P_RNR_GAP],
        help='Only calls at least this far apart count towards Ringing Not Responding (150 = 2 h 30 min). '
             'After this gap with no answer the officer gets an "RNR call not done" popup. 0 = no gap rule.')
    lead_rnr_gap_noon_min = fields.Integer(
        string='Gap - lead came after the midday hour (minutes)', config_parameter=P_GAP_NOON,
        default=DEFAULTS[P_GAP_NOON], help='90 = 1 h 30 min.')
    lead_rnr_gap_eve_min = fields.Integer(
        string='Gap - lead came after the evening hour (minutes)', config_parameter=P_GAP_EVE,
        default=DEFAULTS[P_GAP_EVE], help='30 = 30 min.')
    lead_rnr_day_start = fields.Float(
        string='Working day starts (hour, IST)', config_parameter=P_DAY_START, default=DEFAULTS[P_DAY_START],
        help='10.75 = 10:45 AM. A lead that came earlier is treated as if it came at this time.')
    lead_rnr_day_end = fields.Float(
        string='Working day ends (hour, IST)', config_parameter=P_DAY_END, default=DEFAULTS[P_DAY_END],
        help='19 = 7:00 PM. The gap = time left until this hour / number of RNR calls, between the shortest gap '
             '(evening gap setting) and the longest gap (first gap setting). 0 = use the fixed morning / midday / '
             'evening gaps instead.')
    lead_rnr_genuine_gap = fields.Integer(
        string='Genuine phone calls - shortest gap (minutes)', config_parameter=P_GENUINE, default=DEFAULTS[P_GENUINE],
        help='Calls made through the phone system (Bonvoice) that rang and were not answered count towards Ringing '
             'Not Responding when they are at least this many minutes apart, even if the normal gap is longer. '
             '0 = off, the normal gap is always used.')
    lead_rnr_gap_tolerance = fields.Integer(
        string='Allow a call this many minutes early (minutes)', config_parameter=P_GAP_TOL,
        default=DEFAULTS[P_GAP_TOL], help='A call up to this many minutes short of the gap still counts. 15 = 2h 15m is accepted for a 2h 30m gap.')
    lead_rnr_noon_hour = fields.Integer(string='Midday starts at (hour, IST)', config_parameter=P_NOON_H,
                                        default=DEFAULTS[P_NOON_H])
    lead_rnr_eve_hour = fields.Integer(string='Evening starts at (hour, IST)', config_parameter=P_EVE_H,
                                       default=DEFAULTS[P_EVE_H])
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
