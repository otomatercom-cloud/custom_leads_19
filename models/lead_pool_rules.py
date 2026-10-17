# -*- coding: utf-8 -*-
"""Pool round-robin extras (configured on the active Pool rule):
 1. 'Ringing Not Responding' only after N calls.
 2. A New lead whose quality is changed by its officer moves to the next officer.
 3. A lead not called enough on the day it was assigned moves to another officer next day."""
from datetime import datetime, timedelta
import logging

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

UNWORKED = (False, 'new', 'first_attempt')


class LeadsLogicPoolRules(models.Model):
    _inherit = 'leads.logic'

    auto_reassign_count = fields.Integer(string='Auto Reassignments', default=0, copy=False, readonly=True)
    is_abroad = fields.Boolean(
        string='Abroad Lead', index=True, copy=False, tracking=True,
        help='Tick for a lead living abroad (they usually answer on WhatsApp, not the phone). The lead moves to '
             'the Abroad menu and is left out of the automatic rules: no automatic Ringing Not Responding '
             'after N calls, no automatic reassignment, no RNR popup.')

    def action_mark_abroad(self):
        self.write({'is_abroad': True})
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Abroad'), 'message': _('%s lead(s) moved to the Abroad menu.') % len(self),
                           'type': 'success'}}

    def action_unmark_abroad(self):
        self.write({'is_abroad': False})
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Abroad'), 'message': _('%s lead(s) moved back to Leads.') % len(self),
                           'type': 'success'}}

    def _pool_rule(self):
        rules = self.env['lead.assignment.rule'].sudo().search([('active', '=', True)], order='sequence, id')
        lead = self[:1]
        rule = next((r for r in rules
                     if r.assignment_type != 'attendance_pool' or not lead or r._pool_accepts(lead)), False)
        return rule if rule and rule.assignment_type == 'attendance_pool' else False

    def _check_quality_response(self, vals):
        """Changing the Lead Quality (other than to Ringing Not Responding) needs a Response: either written in
        this save, or by this user within the last 30 minutes and after the lead's previous quality change."""
        rec = self
        if (vals.get('lead_quality') or False) == (rec.lead_quality or False):
            return
        for cmd in vals.get('response_ids') or []:
            if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == 0 and \
                    ((cmd[2] or {}).get('comment') or '').strip():
                return
        since = fields.Datetime.now() - timedelta(minutes=30)
        last = self.env['lead.quality.history'].sudo().search(
            [('lead_id', '=', rec.id)], order='change_date desc', limit=1)
        if last and last.change_date and last.change_date > since:
            since = last.change_date
        if self.env['lead.response'].sudo().search_count([
                ('lead_id', '=', rec.id), ('user_id', '=', self.env.uid), ('create_date', '>=', since)]):
            return
        raise UserError(_("Please add a 💬 Response (what happened on the call) before changing the Lead Quality. "
                          "Only Ringing Not Responding can be set without one."))

    def _rnr_gap_minutes(self):
        """Gap between RNR calls for this lead: depends on the time (IST) the lead came to the officer -
        before the midday hour the full gap, after midday a shorter one, in the evening the shortest."""
        self.ensure_one()
        P = self.env['otm.lead.rule.params']
        base = P.param('custom_leads_19.rnr_call_gap_min')
        if not base:
            return 0
        lead = self.sudo()
        # assigned_date is a plain Date (no time of day): use the exact assignment time when we have it
        since = lead.reassign_date or False
        if not since:
            hist = self.env['lead.assignment.history'].sudo().search(
                [('lead_id', '=', self.id)], order='id desc', limit=1)
            since = hist.assigned_date if hist else False
        if not since:
            since = lead.create_date
        if since and not isinstance(since, datetime):       # still a date: treat as the start of that day (UTC)
            since = datetime.combine(since, datetime.min.time())
        if not since:
            return base
        local = pytz.utc.localize(since).astimezone(pytz.timezone('Asia/Kolkata'))
        hour = local.hour + local.minute / 60.0
        day_end = P.param('custom_leads_19.rnr_day_end')
        if day_end:
            # fair gap: the time left in the working day shared between the RNR calls
            start = P.param('custom_leads_19.rnr_day_start')
            left = (day_end - max(hour, start)) * 60.0
            calls = max(1, P.param('custom_leads_19.rnr_min_calls'))
            lo = P.param('custom_leads_19.rnr_gap_eve_min')
            return int(max(lo, min(base, left / calls)))
        if hour >= P.param('custom_leads_19.rnr_eve_hour'):
            return P.param('custom_leads_19.rnr_gap_eve_min')
        if hour >= P.param('custom_leads_19.rnr_noon_hour'):
            return P.param('custom_leads_19.rnr_gap_noon_min')
        return base

    def _rnr_spaced_calls(self):
        """Calls that count towards Ringing Not Responding: outgoing calls at least the lead's gap apart
        (the first call counts, each next one only if it is that long after the last counted call)."""
        self.ensure_one()
        gap = self._rnr_gap_minutes()
        if not gap:
            return self.call_count
        tol = max(0, self.env['otm.lead.rule.params'].param('custom_leads_19.rnr_gap_tolerance_min') or 0)
        need_secs = max(0, gap - tol) * 60
        gen = self.env['otm.lead.rule.params'].param('custom_leads_19.rnr_genuine_gap_min')
        gen_secs = max(0, min(gen, gap)) * 60 if gen else 0
        calls = sorted(((c.call_time, bool(c.call_uuid)) for c in self.sudo().call_log_ids
                        if c.call_type != 'incoming' and c.call_time), key=lambda x: x[0])
        counted, last, last_genuine = 0, None, False
        for t, genuine in calls:
            if last is None:
                ok = True
            else:
                secs = (t - last).total_seconds()
                # a call from the phone system after a phone-system call only needs the short "genuine" gap
                ok = secs >= need_secs or (gen_secs and genuine and last_genuine and secs >= gen_secs)
            if ok:
                counted += 1
                last, last_genuine = t, genuine
        return counted

    def write(self, vals):
        reassign = self.env['leads.logic']
        rule = False
        if 'lead_quality' in vals and not self.env.context.get('skip_pool_rules') and not self.env.su:
            rule = self._pool_rule()
            new_q = vals.get('lead_quality')
            # one setting for everyone: Settings > Leads > Lead rules
            need = self.env['otm.lead.rule.params'].param('custom_leads_19.rnr_min_calls')
            # every quality change except RNR needs a 💬 Response (what happened on the call)
            if new_q and new_q != 'not_responding' and len(self) == 1 \
                    and not self.env.context.get('otm_odoo17_import') and not self.env.context.get('skip_response_check'):
                self._check_quality_response(vals)
            if need and new_q == 'not_responding':
                for rec in self:
                    if rec.lead_quality == 'not_responding' or rec.is_abroad:
                        continue
                    have = rec._rnr_spaced_calls()
                    if have < need:
                        gap = rec._rnr_gap_minutes()
                        raise UserError(_(
                            "'Ringing Not Responding' needs at least %(need)s calls%(gap)s and this lead has "
                            "only %(have)s. Call the lead again first.") % {
                            'need': need, 'have': have,
                            'gap': (_(', each at least %(h)sh %(m)sm after the previous one') % {
                                'h': gap // 60, 'm': gap % 60}) if gap else ''})
        if rule:
            new_q = vals.get('lead_quality')
            mode = rule.pool_reassign_on_quality
            # company-phone (mobile app) calls reach Odoo a little after the call, so an officer using the
            # app may change quality before the call is synced: do not treat that as "no call" (the
            # time-based "not called within X minutes" rule still covers real no-call leads)
            has_app = bool(self.env['otm.mobile.key'].sudo().search_count(
                [('user_id', '=', self.env.uid), ('active', '=', True)]))
            if mode == 'no_call' and has_app:
                mode = False
            if mode in ('no_call', 'always') and new_q and new_q != 'new':
                for rec in self:
                    if (not rec.is_abroad and rec.lead_quality in (False, 'new') and rec.lead_owner
                            and rec.sudo().lead_owner.user_id.id == self.env.uid
                            and (mode == 'always' or not rec.call_count)):
                        reassign |= rec
        res = super().write(vals)
        for rec in reassign:
            rule._pool_reassign_lead(
                rec, _("quality changed to %s on a new lead") % (
                    dict(rec._fields['lead_quality'].selection).get(rec.lead_quality, rec.lead_quality)))
        return res


class LeadAssignmentRulePoolRules(models.Model):
    _inherit = 'lead.assignment.rule'

    def _pool_reassign_lead(self, lead, reason):
        """Move `lead` to another eligible officer. Returns True when it moved."""
        self.ensure_one()
        lead = lead.sudo()
        old = lead.lead_owner
        if not old or lead.auto_reassign_count >= self.pool_max_reassigns or lead.is_abroad or lead.is_crash_course:
            return False
        # leads created by an incoming call stay with whoever got them
        if lead.leads_source and lead.leads_source.name == 'Incoming Call Leads':
            return False
        Lead = lead.with_context(pool_force=True, pool_exclude_employee_ids=old.ids, skip_pool_rules=True)
        try:
            with self.env.cr.savepoint():
                Lead._auto_assign_lead(Lead)
                self.env.flush_all()
        except Exception as e:  # noqa: BLE001
            _logger.error('Pool reassign of lead %s failed: %s', lead.id, e)
            return False
        lead.invalidate_recordset(['lead_owner'])
        if lead.lead_owner == old or not lead.lead_owner:
            return False
        lead.with_context(skip_pool_rules=True).write({'auto_reassign_count': lead.auto_reassign_count + 1})
        lead.message_post(body=_("Auto-reassigned from %(old)s to %(new)s: %(why)s.") % {
            'old': old.name, 'new': lead.lead_owner.name, 'why': reason})
        self._pool_notify(old, lead.lead_owner, lead, reason)
        return True

    def _pool_notify(self, old, new, lead, reason):
        """Popup (sticky toast) for the officer who lost the lead, and one for the officer who got it."""
        label = '%s%s' % (lead.name or _('Lead'), (' (%s)' % lead.reference_no) if lead.reference_no else '')
        jobs = [
            (old, _('Lead reassigned'), 'danger', _(
                '%(lead)s was taken from you and assigned to %(new)s: %(why)s.') % {
                    'lead': label, 'new': new.name, 'why': reason}),
            (new, _('New lead assigned'), 'warning', _(
                '%(lead)s was reassigned to you from %(old)s.') % {'lead': label, 'old': old.name}),
        ]
        for emp, title, kind, msg in jobs:
            partner = emp.sudo().user_id.partner_id
            if not partner:
                continue
            try:
                self.env['bus.bus'].sudo()._sendone(
                    partner, 'lead_reassign_notice',
                    {'title': title, 'message': msg, 'type': kind, 'lead_id': lead.id, 'open': emp == new})
            except Exception:  # noqa: BLE001 - a notification problem must never block the reassignment
                _logger.exception('Pool reassign popup failed')

    @api.model
    def cron_pool_reassign_uncalled(self):
        """Leads assigned yesterday that did not get the required calls that day go to another officer."""
        rule = self.sudo().search([('active', '=', True)], order='sequence, id', limit=1)
        if not rule or rule.assignment_type != 'attendance_pool' or not rule.pool_uncalled_reassign:
            return
        if not rule._pool_is_open():
            return
        today_start, _end = rule._pool_today_bounds_utc()
        Lead = self.env['leads.logic'].sudo()
        leads = Lead.search([
            ('is_hiring', '=', False), ('is_crash_course', '=', False),
            ('lead_owner', '!=', False), ('state', '!=', 'lost'),
            ('lead_quality', 'in', list(UNWORKED)),
            ('reassign_date', '>=', today_start - timedelta(days=1)), ('reassign_date', '<', today_start),
            ('auto_reassign_count', '<', rule.pool_max_reassigns),
        ] + ([('leads_source', 'in', rule.pool_source_ids.ids)] if rule.pool_source_ids else []), order='reassign_date asc', limit=200)
        moved = 0
        for lead in leads:
            calls = len(lead.call_log_ids.filtered(lambda c: c.call_time and c.call_time >= lead.reassign_date))
            if calls >= rule.pool_min_daily_calls:
                continue
            if not (rule._pool_eligible() - lead.lead_owner):
                break
            if rule._pool_reassign_lead(lead, _("only %(c)s of %(n)s required calls on the assigned day") % {
                    'c': calls, 'n': rule.pool_min_daily_calls}):
                moved += 1
        if moved:
            _logger.info('Pool: %s uncalled lead(s) reassigned to another officer.', moved)


    @api.model
    def cron_pool_reassign_not_called_quickly(self):
        """A New lead with no call at all `pool_first_call_minutes` after assignment goes to another officer."""
        rules = self.sudo().search([('active', '=', True), ('assignment_type', '=', 'attendance_pool'),
                                    ('pool_first_call_reassign', '=', True)], order='sequence, id')
        Lead = self.env['leads.logic'].sudo()
        for rule in rules:
            if not rule._pool_is_open() or not rule.pool_first_call_minutes:
                continue
            now = fields.Datetime.now()
            limit = now - timedelta(minutes=rule.pool_first_call_minutes)
            base_dom = [
                ('is_hiring', '=', False), ('is_crash_course', '=', False),
                ('lead_owner', '!=', False), ('state', '!=', 'lost'),
                ('lead_quality', 'in', [False, 'new']),
                ('auto_reassign_count', '<', rule.pool_max_reassigns),
            ] + ([('leads_source', 'in', rule.pool_source_ids.ids)] if rule.pool_source_ids else [])
            leads = Lead.search(base_dom + [
                '|',
                '&', ('reassign_date', '>=', now - timedelta(days=1)), ('reassign_date', '<=', limit),
                '&', ('reassign_date', '=', False),
                '&', ('create_date', '>=', now - timedelta(days=1)), ('create_date', '<=', limit),
            ], order='id asc', limit=100)
            # leads assigned today to an officer by any rule (source rule, bulk assign, ...) have no reassign_date
            # and may be old records: take the assignment time from the Assignment History
            hist = self.env['lead.assignment.history'].sudo().search([
                ('assigned_date', '>=', now - timedelta(days=1)), ('assigned_date', '<=', limit)], order='id desc')
            hist_ids = list({h.lead_id.id for h in hist if h.lead_id} - set(leads.ids))
            if hist_ids:
                leads |= Lead.search(base_dom + [('id', 'in', hist_ids)], order='id asc', limit=100)
            last_hist = {}
            for h in self.env['lead.assignment.history'].sudo().search(
                    [('lead_id', 'in', leads.ids)], order='id asc'):
                last_hist[h.lead_id.id] = h
            moved = 0
            # the clock only runs while the officer is free and has not yet looked at the lead:
            #  - after the end of the officer's latest call (a long call on another lead pauses it)
            #  - after the officer opened the lead
            #  - company-phone (app) users get extra minutes: their calls reach Odoo after a sync delay
            from .call_report import _parse_duration_seconds
            owners = leads.mapped('lead_owner.user_id')
            app_users = set(self.env['otm.mobile.key'].sudo().search(
                [('user_id', 'in', owners.ids), ('active', '=', True)]).mapped('user_id').ids)
            busy_until = {}
            for c in self.env['lead.call.log'].sudo().search(
                    [('user_id', 'in', owners.ids), ('call_time', '>=', now - timedelta(hours=4))]):
                end = c.call_time + timedelta(seconds=_parse_duration_seconds(c.duration))
                if end > busy_until.get(c.user_id.id, datetime.min):
                    busy_until[c.user_id.id] = end
            for lead in leads:
                since = lead.reassign_date or lead.create_date
                h = last_hist.get(lead.id)
                if h and h.assigned_date and h.owner_id == lead.lead_owner and h.assigned_date > since:
                    since = h.assigned_date
                if since < now - timedelta(days=1):
                    continue
                if lead.call_log_ids.filtered(lambda c: (c.call_time or c.create_date) >= since):
                    continue
                owner_user = lead.lead_owner.user_id
                wait_from = since
                if busy_until.get(owner_user.id) and busy_until[owner_user.id] > wait_from:
                    wait_from = busy_until[owner_user.id]
                if lead.last_opened_on and lead.last_opened_by == owner_user and lead.last_opened_on > wait_from:
                    wait_from = lead.last_opened_on
                grace = (rule.pool_app_grace_min or 0) if owner_user.id in app_users else 0
                if now < wait_from + timedelta(minutes=rule.pool_first_call_minutes + grace):
                    continue
                if not (rule._pool_eligible() - lead.lead_owner):
                    break
                if rule._pool_reassign_lead(lead, _("not called within %s minutes of assignment")
                                            % rule.pool_first_call_minutes):
                    moved += 1
            if moved:
                _logger.info('Pool: %s lead(s) not called in time were reassigned.', moved)


class LeadCallLogPoolRules(models.Model):
    _inherit = 'lead.call.log'

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if not self.env.context.get('otm_odoo17_import'):
            recs._pool_auto_rnr()
            recs._incoming_assign_owner()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if 'call_status' in vals or 'duration' in vals or 'user_id' in vals:
            self._pool_auto_rnr()
            if not self.env.context.get('otm_odoo17_import'):
                self._incoming_assign_owner()
        return res

    def _incoming_assign_owner(self):
        """An incoming call answered by an officer (or a connected call-back to an unowned lead): that officer gets the lead when it is a new
        'Incoming Call Leads' lead or has no owner yet. Leads owned by someone else are left alone."""
        from .call_report import _parse_duration_seconds, _is_connected
        try:
            for log in self.sudo():
                lead, user = log.lead_id, log.user_id
                if not lead or lead.state == 'lost':
                    continue
                # answered incoming call, or a connected call-back (outgoing) on a lead nobody owns yet
                if log.call_type != 'incoming' and not (log.call_type == 'outgoing' and not lead.lead_owner):
                    continue
                if not _is_connected(log.call_status, _parse_duration_seconds(log.duration)):
                    continue
                if not user:
                    _logger.warning('Incoming auto-assign: call %s (lead %s) answered but no officer '
                                    'matched the agent number - check the user\'s Bonvoice/Voxbay number.',
                                    log.id, lead.id)
                    continue
                emp = user.employee_id
                if not emp:
                    _logger.warning('Incoming auto-assign: user %s has no employee - lead %s not assigned.',
                                    user.login, lead.id)
                    continue
                if lead.lead_owner == emp:
                    continue
                incoming_src = lead.leads_source and lead.leads_source.name == 'Incoming Call Leads'
                if lead.lead_owner and not incoming_src:
                    continue
                old = lead.lead_owner
                lead.with_context(skip_pool_rules=True, urgent_lead_skip=True).write({'lead_owner': emp.id})
                lead.message_post(body=_("Incoming call answered by %(new)s: lead assigned to %(new)s%(old)s.") % {
                    'new': emp.name, 'old': (_(' (was %s)') % old.name) if old else ''})
        except Exception:  # noqa: BLE001 - never block call logging
            _logger.exception('Incoming call auto-assign failed')

    def _pool_auto_rnr(self):
        """New / First Attempt lead with N calls and none answered -> Ringing Not Responding."""
        from .call_report import _parse_duration_seconds
        try:
            need = self.env['otm.lead.rule.params'].param('custom_leads_19.rnr_min_calls')
            if not need:
                return
            for lead in self.mapped('lead_id').sudo():
                if lead.lead_quality not in UNWORKED or lead.state == 'lost' or lead.is_abroad:
                    continue
                rule = lead._pool_rule()
                if not rule or not rule.pool_auto_rnr:
                    continue
                calls = lead.call_log_ids.filtered(lambda c: c.call_type != 'incoming')
                spaced = lead._rnr_spaced_calls()
                if spaced < need:
                    continue
                if any(_parse_duration_seconds(c.duration) > 0 for c in lead.call_log_ids):
                    continue
                lead.with_context(skip_pool_rules=True).write({'lead_quality': 'not_responding'})
                lead.message_post(body=_("Set to Ringing Not Responding automatically: %s calls, none answered.")
                                  % spaced)
        except Exception:  # noqa: BLE001 - never block call logging
            _logger.exception('Pool auto RNR failed')
