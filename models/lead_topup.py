# -*- coding: utf-8 -*-
"""Top-up pool: an officer who has finished today's calls is given more leads automatically.

Pool = unassigned leads that are ticked "Top-up pool" or come from a source marked "Feeds the top-up pool".
Pool leads are not given out by the normal assignment rule - only by this feature."""
import logging
from datetime import timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

P = 'custom_leads_19.topup_'
UNWORKED = (False, 'new', 'first_attempt')


class LeadsSourcesTopup(models.Model):
    _inherit = 'leads.sources'

    topup_pool = fields.Boolean(
        string='Feeds the top-up pool', tracking=True,
        help='Unassigned leads of this source are not given out by the normal assignment. They wait in the '
             'top-up pool and go to an officer who has finished the day\'s calls.')


class ResConfigSettingsTopup(models.TransientModel):
    _inherit = 'res.config.settings'

    topup_enabled = fields.Boolean(string='Give leads to officers who finish their calls',
                                   config_parameter=P + 'enabled')
    topup_pending_max = fields.Integer(string='Leads left to call at most', config_parameter=P + 'pending_max',
                                       default=0)
    topup_batch = fields.Integer(string='Leads given each time', config_parameter=P + 'batch', default=20)
    topup_daily_cap = fields.Integer(string='Maximum leads per officer per day', config_parameter=P + 'daily_cap',
                                     default=60)
    topup_min_calls = fields.Integer(string='Calls made today before the first top-up',
                                     config_parameter=P + 'min_calls', default=20)
    topup_cooldown = fields.Integer(string='Minutes between two top-ups', config_parameter=P + 'cooldown',
                                    default=15)
    topup_attendance = fields.Boolean(string='Only officers who signed in today', config_parameter=P + 'attendance',
                                      default=True)
    topup_from_hour = fields.Integer(string='From hour', config_parameter=P + 'from_hour', default=9)
    topup_to_hour = fields.Integer(string='Until hour', config_parameter=P + 'to_hour', default=19)

    def action_topup_run_now(self):
        self.execute()
        res = self.env['leads.logic'].cron_topup(force=True)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Top-up'), 'message': res or _('Nothing to do.'), 'type': 'info',
                           'sticky': True}}


class LeadsLogicTopup(models.Model):
    _inherit = 'leads.logic'

    in_topup_pool = fields.Boolean(
        string='Top-up pool', index=True, copy=False, tracking=True,
        help='Not given out by the normal assignment. Waits to be given to an officer who has finished their calls.')
    topup_pool_lead = fields.Boolean(compute='_compute_topup_pool_lead', store=True, index=True)
    topup_assigned_dt = fields.Datetime(string='Top-up given on', copy=False, index=True)

    @api.depends('in_topup_pool', 'leads_source.topup_pool')
    def _compute_topup_pool_lead(self):
        for rec in self:
            rec.topup_pool_lead = bool(rec.in_topup_pool or rec.leads_source.topup_pool)

    def action_add_topup_pool(self):
        self.write({'in_topup_pool': True})
        owned = len(self.filtered('lead_owner'))
        msg = _('%s lead(s) added to the top-up pool.') % len(self)
        if owned:
            msg += ' ' + _('%s of them still belong to an officer and are given out only when that officer is removed '
                           '- use "Add to Top-up pool and take back" to unassign them.') % owned
        return self._topup_notify_ui(msg)

    def action_add_topup_pool_take_back(self):
        """Manager / Super Admin: put the leads in the pool AND remove their current officer so they can be given out."""
        user = self.env.user
        if not (user.has_group('custom_leads_19.group_lead_manager') or user.has_group('custom_leads_19.group_super_admin')):
            raise UserError(_('Only a manager can take leads back from officers.'))
        taken = self.filtered('lead_owner')
        self.with_context(skip_pool_rules=True, urgent_lead_skip=True).write({'in_topup_pool': True, 'lead_owner': False})
        for lead in taken:
            lead.message_post(body=_('Taken back into the top-up pool by %s.') % user.name)
        return self._topup_notify_ui(_('%s lead(s) in the top-up pool, %s taken back from officers.') % (
            len(self), len(taken)))

    def action_remove_topup_pool(self):
        self.write({'in_topup_pool': False})
        return self._topup_notify_ui(_('%s lead(s) removed from the top-up pool.') % len(self))

    @api.model
    def _topup_notify_ui(self, msg):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Top-up pool'), 'message': msg, 'type': 'success', 'sticky': False}}

    def _auto_assign_lead(self, lead):
        """Pool leads wait for the top-up; the normal rule must not hand them out."""
        one = lead[:1] if lead else lead
        if one and not self.env.context.get('topup_assign') and (one.in_topup_pool or one.leads_source.topup_pool):
            return
        return super()._auto_assign_lead(lead)

    # ------------------------------------------------------------------ #
    @api.model
    def _topup_cfg(self):
        icp = self.env['ir.config_parameter'].sudo()

        def num(key, default):
            v = (icp.get_param(P + key) or '').strip()
            return int(v) if v.lstrip('-').isdigit() else default
        return {
            'on': icp.get_param(P + 'enabled') in ('True', '1', 'true'),
            'pending_max': num('pending_max', 0), 'batch': num('batch', 20), 'cap': num('daily_cap', 60),
            'min_calls': num('min_calls', 20), 'cooldown': num('cooldown', 15),
            'attendance': (icp.get_param(P + 'attendance') or 'True') in ('True', '1', 'true'),
            'from': num('from_hour', 9), 'to': num('to_hour', 19),
        }

    @api.model
    def _topup_pool_domain(self):
        return [('lead_owner', '=', False), ('topup_pool_lead', '=', True), ('state', '!=', 'lost'),
                ('is_abroad', '=', False), ('admission_status', '=', False),
                ('lead_stage_category', 'not in', ['admission_done', 'junk'])]

    @api.model
    def _topup_remaining(self, emp, start_utc, now):
        """How many leads the officer still has to call today (queue, else fresh leads, + follow-ups due today)."""
        Call = self.env['lead.call.log'].sudo()
        today = fields.Date.today()
        queue = self.search([('lead_owner', '=', emp.id), ('daily_queue_date', '=', today)])
        if queue:
            called = {r[0].id for r in Call._read_group(
                [('lead_id', 'in', queue.ids), ('call_time', '>=', start_utc)], ['lead_id'])}
            left = len(queue.filtered(lambda l: not l.daily_call_done and l.id not in called))
        else:
            left = self.search_count([
                ('lead_owner', '=', emp.id), ('lead_quality', 'in', list(UNWORKED)), ('state', '!=', 'lost'),
                ('first_called_dt', '=', False), ('is_abroad', '=', False),
                ('assigned_date', '>=', today - timedelta(days=3))])
        left += self.env['lead.followup'].sudo().search_count([
            ('lead_id.lead_owner', '=', emp.id), ('status', '=', 'scheduled'),
            ('next_followup_date', '>=', start_utc), ('next_followup_date', '<=', now)])
        return left

    @api.model
    def _topup_signed_in(self, emps):
        if 'hr.attendance' not in self.env:
            return set(emps.ids)
        start = self._rd_utc(fields.Date.context_today(self.with_context(tz=self._rd_tzname())))
        return set(self.env['hr.attendance'].sudo().search([
            ('employee_id', 'in', emps.ids), ('check_in', '>=', start), ('check_out', '=', False)]
        ).mapped('employee_id').ids)

    @api.model
    def cron_topup(self, force=False):
        cfg = self._topup_cfg()
        if not (cfg['on'] or force):
            return ''
        tz = pytz.timezone(self._rd_tzname())
        now = fields.Datetime.now()
        local = pytz.utc.localize(now).astimezone(tz)
        if not force and not (cfg['from'] <= local.hour < cfg['to']):
            return ''
        start_utc = self._rd_utc(local.date())
        Lead = self.sudo()
        members = self.env['lead.team.member'].sudo().search([('team_id.active', '=', True)])
        emps = members.mapped('employee_id').filtered(lambda e: e.user_id and e.user_id.active)
        if cfg['attendance']:
            present = self._topup_signed_in(emps)
            emps = emps.filtered(lambda e: e.id in present)
        given_today = {}
        for emp, n in Lead._read_group([('lead_owner', 'in', emps.ids), ('topup_assigned_dt', '>=', start_utc)],
                                       ['lead_owner'], ['__count']):
            given_today[emp.id] = n
        emps = emps.sorted(lambda e: (given_today.get(e.id, 0), e.id))     # fewest top-ups first
        done, empty = [], False
        for emp in emps:
            got = given_today.get(emp.id, 0)
            if got >= cfg['cap']:
                continue
            last = Lead.search([('lead_owner', '=', emp.id), ('topup_assigned_dt', '!=', False)],
                               order='topup_assigned_dt desc', limit=1).topup_assigned_dt
            if last and last > now - timedelta(minutes=cfg['cooldown']):
                continue
            calls = self.env['lead.call.log'].sudo().search_count([
                ('user_id', '=', emp.user_id.id), ('call_time', '>=', start_utc)])
            if calls < cfg['min_calls']:
                continue
            if Lead._topup_remaining(emp, start_utc, now) > cfg['pending_max']:
                continue
            take = Lead.search(Lead._topup_pool_domain(), order='call_score desc, create_date desc, id desc',
                               limit=min(cfg['batch'], cfg['cap'] - got))
            if not take:
                empty = True
                break
            take.with_context(skip_pool_rules=True, urgent_lead_skip=True, topup_assign=True,
                              tracking_disable=True, mail_notrigger=True).write({
                'lead_owner': emp.id, 'daily_queue_date': fields.Date.today(), 'daily_call_done': False,
                'daily_call_sequence': 0, 'assigned_date': fields.Date.today(), 'topup_assigned_dt': now})
            for lead in take:
                lead.with_context(mail_notrigger=True).message_post(
                    body=_('Given from the top-up pool to %s (finished the calls for today).') % emp.name)
            self._topup_notify(emp, take)
            done.append('%s +%s' % (emp.name, len(take)))
            self.env.cr.commit()
        if empty:
            self._topup_empty_notice()
        if done:
            _logger.info('Top-up: %s', ', '.join(done))
        return (_('Given: %s.') % ', '.join(done)) if done else (
            _('The top-up pool is empty.') if empty else _('No officer needs leads right now.'))

    @api.model
    def _topup_notify(self, emp, leads):
        partner = emp.sudo().user_id.partner_id
        if not partner:
            return
        try:
            self.env['bus.bus'].sudo()._sendone(partner, 'lead_reassign_notice', {
                'title': _('New leads for you'), 'type': 'success', 'lead_id': leads[:1].id, 'open': False,
                'message': _('You finished your calls. %s new leads were added to your list.') % len(leads)})
        except Exception:  # noqa: BLE001
            _logger.exception('Top-up popup failed')

    @api.model
    def _topup_empty_notice(self):
        icp = self.env['ir.config_parameter'].sudo()
        today = str(fields.Date.today())
        if icp.get_param(P + 'empty_day') == today:
            return
        icp.set_param(P + 'empty_day', today)
        groups = [self.env.ref('custom_leads_19.group_lead_manager').id,
                  self.env.ref('custom_leads_19.group_super_admin').id]
        for u in self.env['res.users'].sudo().search([('group_ids', 'in', groups)]):
            try:
                self.env['bus.bus'].sudo()._sendone(u.partner_id, 'lead_reassign_notice', {
                    'title': _('Top-up pool is empty'), 'type': 'warning', 'lead_id': False, 'open': False,
                    'message': _('Officers have finished their calls but there are no leads in the top-up pool. '
                                 'Add leads to the pool.')})
            except Exception:  # noqa: BLE001
                _logger.exception('Top-up empty notice failed')
