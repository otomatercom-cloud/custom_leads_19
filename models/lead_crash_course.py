# -*- coding: utf-8 -*-
"""Crash Course: an admission officer can move a lead to the Crash Course menu.

The whole option is switched on / off in Settings > Leads > Crash Course. It uses an Odoo feature group
(group_crash_course_on, added to all internal users while the option is ON), so when the option is OFF the checkbox,
the buttons, the filter and the Crash Course menu disappear, and crash-course leads show in the normal Leads list again.
Crash-course leads are left out of the automatic pool / reassign / top-up rules (like Abroad leads)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

GROUP = 'custom_leads_19.group_crash_course_on'


class LeadsLogicCrashCourse(models.Model):
    _inherit = 'leads.logic'

    is_crash_course = fields.Boolean(
        string='Crash Course', index=True, copy=False, tracking=True,
        help='Tick when the student wants the Crash Course. The lead moves to the Crash Course menu and is left '
             'out of the automatic assignment and reassignment rules.')
    in_crash_menu = fields.Boolean(compute='_compute_in_crash_menu', search='_search_in_crash_menu')

    @api.model
    def _crash_enabled(self):
        group = self.env.ref(GROUP, raise_if_not_found=False)
        if not group:
            return False
        return group in self.env.ref('base.group_user').sudo().implied_ids

    def _compute_in_crash_menu(self):
        on = self._crash_enabled()
        for rec in self:
            rec.in_crash_menu = bool(on and rec.is_crash_course)

    def _search_in_crash_menu(self, operator, value):
        """Crash-course leads are in the Crash Course menu only while the option is ON; while it is OFF they
        show in the normal Leads list again."""
        want = bool(value) if operator in ('=', 'in') else not bool(value)
        if self._crash_enabled():
            return [('is_crash_course', '=', want)]
        return [('id', '=', 0)] if want else [('id', '!=', 0)]

    def action_move_crash_course(self):
        if not self._crash_enabled():
            raise UserError(_('The Crash Course option is switched off in Settings.'))
        self.write({'is_crash_course': True})
        return self._crash_notice(_('%s lead(s) moved to the Crash Course menu.') % len(self))

    def action_move_back_crash_course(self):
        self.write({'is_crash_course': False})
        return self._crash_notice(_('%s lead(s) moved back to Leads.') % len(self))

    @api.model
    def _crash_notice(self, msg):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Crash Course'), 'message': msg, 'type': 'success'}}


class ResConfigSettingsCrashCourse(models.TransientModel):
    _inherit = 'res.config.settings'

    group_crash_course_on = fields.Boolean(
        string='Crash Course option', implied_group=GROUP,
        help='ON: officers can move a lead to the Crash Course menu. OFF: the option and the menu are hidden.')
