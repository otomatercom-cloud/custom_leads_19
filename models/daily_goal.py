# -*- coding: utf-8 -*-
"""Daily call goal: one number set by an admin in Settings, shown to every
officer on the Next.js dashboard (and usable by any other screen)."""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError

P_GOAL = 'custom_leads_19.daily_call_goal'
DEFAULT_GOAL = 50


class ResConfigSettingsDailyGoal(models.TransientModel):
    _inherit = 'res.config.settings'

    daily_call_goal = fields.Integer(
        string='Daily call goal', config_parameter=P_GOAL, default=DEFAULT_GOAL,
        help='Calls each admission officer is expected to make per day.')


class LeadsLogicDailyGoal(models.Model):
    _inherit = 'leads.logic'

    @api.model
    def get_daily_call_goal(self):
        """Readable by every internal user (ir.config_parameter is not)."""
        raw = self.env['ir.config_parameter'].sudo().get_param(P_GOAL)
        try:
            return max(int(raw), 1) if raw else DEFAULT_GOAL
        except (TypeError, ValueError):
            return DEFAULT_GOAL

    @api.model
    def set_daily_call_goal(self, goal):
        user = self.env.user
        if not (user.has_group('base.group_system')
                or user.has_group('custom_leads_19.group_lead_manager')
                or user.has_group('custom_leads_19.group_lead_team_lead')
                or user.has_group('custom_leads_19.group_super_admin')):
            raise AccessError(_('Only managers can change the daily call goal.'))
        goal = max(1, min(int(goal), 1000))
        self.env['ir.config_parameter'].sudo().set_param(P_GOAL, str(goal))
        return goal
