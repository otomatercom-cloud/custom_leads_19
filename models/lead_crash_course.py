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

    def _crash_pick_head(self):
        """The Crash Head (employee) with the fewest crash-course leads - leads are shared out evenly."""
        grp = self.env.ref('custom_leads_19.group_crash_head', raise_if_not_found=False)
        if not grp:
            return self.env['hr.employee']
        users = self.env['res.users'].sudo().search([('group_ids', 'in', grp.id), ('active', '=', True)])
        emps = self.env['hr.employee'].sudo().search([('user_id', 'in', users.ids)])
        if not emps:
            return emps
        load = {e.id: self.sudo().search_count([('lead_owner', '=', e.id), ('is_crash_course', '=', True)])
                for e in emps}
        return min(emps, key=lambda e: (load[e.id], e.id))

    def action_move_crash_course(self):
        if not self._crash_enabled():
            raise UserError(_('The Crash Course option is switched off in Settings.'))
        moved = 0
        head = self.env['hr.employee']
        for rec in self.sudo():
            head = rec._crash_pick_head()
            vals = {'is_crash_course': True}
            if head and rec.lead_owner != head:
                vals['lead_owner'] = head.id
                rec.message_post(body=_('Moved to Crash Course. Assigned to Crash Head %s (was %s).') % (
                    head.name, rec.lead_owner.name or '-'))
            rec.with_context(skip_pool_rules=True).write(vals)
            moved += 1
        msg = _('%s lead(s) moved to the Crash Course menu.') % moved
        if head:
            msg += ' ' + _('Assigned to Crash Head.')
        else:
            msg += ' ' + _('No Crash Head user found - owner not changed.')
        res = self._crash_notice(msg)
        # the officer may no longer have access to this lead: go back to the Leads list
        if head and not self.env.user.has_group('custom_leads_19.group_crash_head') \
                and not self._user_can_reassign():
            res['params']['next'] = self.env['ir.actions.act_window']._for_xml_id(
                'custom_leads_19.action_leads_logic')
        return res

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
