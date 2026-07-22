# -*- coding: utf-8 -*-
"""
Call Report — per-officer / per-Team-Lead call activity report.

Data source : lead.call.log  (every Voxbay / Bonvoice / kanban-timer /
              manual call writes a row here with user_id + call_time)
Team roles  : lead.team  (team_lead_ids)  +  lead.team.member (officers)

Visibility:
    * Super Admin / Manager / Branch Head  -> all teams + unassigned callers
    * Team Lead                            -> own team(s) only (incl. self)
    * Admission Officer / Tele Caller      -> own calls only
"""
import logging
import pytz
from datetime import datetime, time, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


def _parse_duration_seconds(value):
    """Parse the Char duration field into seconds.

    Handles: '' / None, '85' (plain seconds), 'MM:SS', 'HH:MM:SS'.
    Never raises — returns 0 on anything unparseable.
    """
    if not value:
        return 0
    value = str(value).strip()
    if not value:
        return 0
    try:
        if ':' in value:
            parts = [int(float(p or 0)) for p in value.split(':')]
            if len(parts) == 2:                     # MM:SS
                return parts[0] * 60 + parts[1]
            if len(parts) == 3:                     # HH:MM:SS
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
            return 0
        return int(float(value))                    # plain seconds
    except (ValueError, TypeError):
        return 0


def _fmt_duration(seconds):
    """Seconds -> 'HH:MM:SS' string."""
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%02d" % (h, m, s)


_CONNECTED_KEYWORDS = ('answer', 'connect', 'success', 'complete', 'received')
_NOT_CONNECTED_KEYWORDS = ('noanswer', 'no answer', 'no_answer', 'busy',
                           'cancel', 'congestion', 'chanunavail', 'fail',
                           'not attended', 'not_attended')


def _is_connected(status, duration_seconds):
    """Heuristic: a call is 'connected' if it has talk time, or the status
    is positive. Negative statuses are checked FIRST because Voxbay's
    'NOANSWER' would otherwise match the 'answer' keyword."""
    if duration_seconds > 0:
        return True
    if status:
        s = str(status).lower()
        if any(k in s for k in _NOT_CONNECTED_KEYWORDS):
            return False
        return any(k in s for k in _CONNECTED_KEYWORDS)
    return False


class LeadCallLogReport(models.Model):
    _inherit = "lead.call.log"

    # ------------------------------------------------------------------
    # Date range helpers (user-timezone aware)
    # ------------------------------------------------------------------
    @api.model
    def _report_utc_bounds(self, date_from, date_to):
        """Convert 'YYYY-MM-DD' date strings (user's local dates) into
        naive-UTC datetime bounds for querying call_time."""
        tz_name = self.env.user.tz or self.env.context.get('tz') or 'Asia/Kolkata'
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.timezone('Asia/Kolkata')

        today_local = datetime.now(tz).date()
        try:
            d_from = fields.Date.from_string(date_from) if date_from else today_local
        except Exception:
            d_from = today_local
        try:
            d_to = fields.Date.from_string(date_to) if date_to else today_local
        except Exception:
            d_to = today_local
        if d_to < d_from:
            d_from, d_to = d_to, d_from

        start_local = tz.localize(datetime.combine(d_from, time.min))
        end_local = tz.localize(datetime.combine(d_to, time.max))
        start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)
        return d_from, d_to, start_utc, end_utc

    # ------------------------------------------------------------------
    # Role / scope resolution
    # ------------------------------------------------------------------
    @api.model
    def _report_scope(self):
        """Return (scope, allowed_teams, allowed_user_ids).

        scope: 'all' | 'team' | 'own'
        """
        user = self.env.user
        if (user.has_group('custom_leads_19.group_super_admin')
                or user.has_group('custom_leads_19.group_lead_manager')
                or user.has_group('custom_leads_19.group_lead_branch_head')):
            return 'all', self.env['lead.team'].sudo().search([]), None

        employee = user.employee_id
        if user.has_group('custom_leads_19.group_lead_team_lead') and employee:
            teams = self.env['lead.team'].sudo().search(
                [('team_lead_ids', 'in', employee.id)])
            if teams:
                allowed = set()
                for team in teams:
                    allowed |= set(
                        team.team_lead_ids.mapped('user_id').ids)
                    allowed |= set(
                        team.member_ids.mapped('user_id').ids)
                allowed.add(user.id)
                return 'team', teams, allowed

        return 'own', self.env['lead.team'].sudo().browse(), {user.id}

    # ------------------------------------------------------------------
    # Assigned leads (current ownership, any date, any state)
    # ------------------------------------------------------------------
    @api.model
    def _assigned_counts(self, allowed_user_ids=None):
        """res.users id -> count of leads.logic currently owned (lead_owner)
        by that user's linked hr.employee. Snapshot of *current* assignment
        — not scoped to the report's date range, since ownership can predate
        it. Restricted to allowed_user_ids when a scope is given (TL/officer
        visibility), so a TL never sees another team's assigned totals."""
        Lead = self.env['leads.logic'].sudo()
        grouped = Lead.read_group(
            [('lead_owner', '!=', False)], ['lead_owner'], ['lead_owner'])
        emp_counts = {g['lead_owner'][0]: g['lead_owner_count'] for g in grouped}
        if not emp_counts:
            return {}
        employees = self.env['hr.employee'].sudo().browse(list(emp_counts.keys()))
        result = {}
        for emp in employees:
            if not emp.user_id:
                continue
            if allowed_user_ids is not None and emp.user_id.id not in allowed_user_ids:
                continue
            result[emp.user_id.id] = result.get(emp.user_id.id, 0) + emp_counts.get(emp.id, 0)
        return result

    # ------------------------------------------------------------------
    # Main dashboard RPC
    # ------------------------------------------------------------------
    @api.model
    def get_call_report(self, date_from=None, date_to=None):
        d_from, d_to, start_utc, end_utc = self._report_utc_bounds(date_from, date_to)
        scope, teams, allowed_user_ids = self._report_scope()
        assigned_map = self._assigned_counts(allowed_user_ids)

        domain = [('call_time', '>=', start_utc), ('call_time', '<=', end_utc)]
        if allowed_user_ids is not None:
            domain.append(('user_id', 'in', list(allowed_user_ids)))

        logs = self.sudo().search_read(
            domain,
            ['user_id', 'lead_id', 'call_type', 'call_status', 'duration'],
            limit=None,
        )

        # ---- aggregate per user -------------------------------------
        per_user = {}
        for log in logs:
            if not log.get('user_id'):
                continue
            uid = log['user_id'][0]
            uname = log['user_id'][1]
            rec = per_user.setdefault(uid, {
                'user_id': uid, 'name': uname,
                'calls': 0, 'outgoing': 0, 'incoming': 0,
                'connected': 0, 'not_connected': 0,
                'duration_seconds': 0, 'lead_ids': set(),
            })
            rec['calls'] += 1
            ctype = log.get('call_type')
            if ctype == 'incoming':
                rec['incoming'] += 1
            else:
                rec['outgoing'] += 1
            dur = _parse_duration_seconds(log.get('duration'))
            rec['duration_seconds'] += dur
            if _is_connected(log.get('call_status'), dur):
                rec['connected'] += 1
            else:
                rec['not_connected'] += 1
            if log.get('lead_id'):
                rec['lead_ids'].add(log['lead_id'][0])

        def make_row(uid, name, role, tl_name=''):
            base = per_user.get(uid) or {
                'calls': 0, 'outgoing': 0, 'incoming': 0,
                'connected': 0, 'not_connected': 0,
                'duration_seconds': 0, 'lead_ids': set(),
            }
            calls = base['calls']
            secs = base['duration_seconds']
            called_leads = len(base['lead_ids'])
            assigned = assigned_map.get(uid, 0)
            # Pending = currently-assigned leads this officer hasn't called
            # in the selected period. Clamped at 0: a lead can show up as
            # "called" here (call log) while no longer being "assigned"
            # (reassigned/lost since), which would otherwise go negative.
            pending = max(0, assigned - called_leads)
            return {
                'user_id': uid,
                'name': name,
                'role': role,                       # 'tl' | 'officer'
                'tl_name': tl_name,
                'calls': calls,
                'outgoing': base['outgoing'],
                'incoming': base['incoming'],
                'connected': base['connected'],
                'not_connected': base['not_connected'],
                'unique_leads': called_leads,
                'assigned': assigned,
                'pending': pending,
                'duration': _fmt_duration(secs),
                'avg_duration': _fmt_duration(secs / calls) if calls else '00:00:00',
            }

        # ---- build team blocks --------------------------------------
        team_blocks = []
        seen_user_ids = set()
        all_rows = []  # every row actually shown, for assigned/pending totals
        for team in teams:
            rows = []
            for tl_emp in team.team_lead_ids:
                tl_user = tl_emp.user_id
                if not tl_user:
                    continue
                if allowed_user_ids is not None and tl_user.id not in allowed_user_ids:
                    continue
                row = make_row(tl_user.id, tl_emp.name, 'tl')
                rows.append(row)
                all_rows.append(row)
                seen_user_ids.add(tl_user.id)
            for member in team.member_ids:
                m_user = member.user_id
                if not m_user:
                    continue
                if allowed_user_ids is not None and m_user.id not in allowed_user_ids:
                    continue
                row = make_row(
                    m_user.id, member.employee_id.name, 'officer',
                    member.team_lead_id.name or '')
                rows.append(row)
                all_rows.append(row)
                seen_user_ids.add(m_user.id)
            if not rows:
                continue
            team_blocks.append({
                'id': team.id,
                'name': team.name,
                'total_calls': sum(r['calls'] for r in rows),
                'total_connected': sum(r['connected'] for r in rows),
                'total_assigned': sum(r['assigned'] for r in rows),
                'total_pending': sum(r['pending'] for r in rows),
                'rows': rows,
            })

        # ---- callers with activity but not in any team ---------------
        others = []
        for uid, rec in per_user.items():
            if uid in seen_user_ids:
                continue
            if allowed_user_ids is not None and uid not in allowed_user_ids:
                continue
            row = make_row(uid, rec['name'], 'officer')
            others.append(row)
            all_rows.append(row)
        others.sort(key=lambda r: -r['calls'])

        # ---- summary (distinct users, so TL in 2 teams not doubled) --
        total_calls = sum(r['calls'] for r in per_user.values())
        summary = {
            'total_calls': total_calls,
            'outgoing': sum(r['outgoing'] for r in per_user.values()),
            'incoming': sum(r['incoming'] for r in per_user.values()),
            'connected': sum(r['connected'] for r in per_user.values()),
            'not_connected': sum(r['not_connected'] for r in per_user.values()),
            'unique_leads': len(set().union(*[r['lead_ids'] for r in per_user.values()])) if per_user else 0,
            'active_callers': len(per_user),
            'total_duration': _fmt_duration(
                sum(r['duration_seconds'] for r in per_user.values())),
            # Assigned/pending come from all_rows (every officer/TL shown,
            # not just ones with call activity) so an officer sitting on
            # assigned leads with zero calls still counts toward pending.
            'total_assigned': sum(r['assigned'] for r in all_rows),
            'total_pending': sum(r['pending'] for r in all_rows),
        }

        return {
            'date_from': fields.Date.to_string(d_from),
            'date_to': fields.Date.to_string(d_to),
            'scope': scope,
            'summary': summary,
            'teams': team_blocks,
            'others': others,
        }

    # ------------------------------------------------------------------
    # Officer drill-down: lead-level detail (called or assigned)
    # ------------------------------------------------------------------
    @api.model
    def get_officer_lead_detail(self, employee_id, mode='called'):
        """Lead-level detail for one officer, for the Officer Performance
        drill-down.

        mode='called'   -> every lead that has a lead.call.log row logged
                            by this officer (i.e. they actually called it).
        mode='assigned' -> every lead currently owned by this officer
                            (leads.logic.lead_owner), called or not.

        Each row reports: the lead's CURRENT quality, the quality this
        specific officer last set on it (from lead.quality.history — quality
        changes made by other officers/TLs on the same lead are not counted
        here), when they last called it, and whether it has since resulted
        in an admission.
        """
        employee = self.env['hr.employee'].sudo().browse(employee_id)
        if not employee.exists():
            return {'employee_name': '', 'mode': mode, 'total': 0,
                    'admitted': 0, 'rows': []}
        user = employee.user_id

        # Same visibility rule as get_call_report: managers/super/branch
        # heads see everyone, a TL sees their own team, an officer sees
        # only themself.
        scope, _teams, allowed_user_ids = self._report_scope()
        if allowed_user_ids is not None:
            if not user or user.id not in allowed_user_ids:
                return {'employee_name': employee.name, 'mode': mode,
                        'total': 0, 'admitted': 0, 'rows': [],
                        'error': 'not_authorized'}

        Lead = self.env['leads.logic'].sudo()
        if mode == 'assigned':
            leads = Lead.search([('lead_owner', '=', employee.id)])
        else:
            if not user:
                return {'employee_name': employee.name, 'mode': mode,
                        'total': 0, 'admitted': 0, 'rows': []}
            log_lead_ids = self.sudo().search(
                [('user_id', '=', user.id)]).mapped('lead_id').ids
            leads = Lead.browse(log_lead_ids)

        if not leads:
            return {'employee_name': employee.name, 'mode': mode,
                    'total': 0, 'admitted': 0, 'rows': []}

        # Last call this officer made on each lead (only if they have a
        # linked user — otherwise there's nothing to match in the log).
        last_call = {}
        if user:
            logs = self.sudo().search_read(
                [('lead_id', 'in', leads.ids), ('user_id', '=', user.id)],
                ['lead_id', 'call_time', 'call_status'], order='call_time asc')
            for l in logs:
                last_call[l['lead_id'][0]] = {
                    'call_time': l['call_time'],
                    'call_status': l.get('call_status') or '',
                }

        # Latest quality *this officer* set on each lead (not whoever set it
        # last overall — history rows are per-user, so this is naturally
        # scoped to their own changes already).
        last_quality = {}
        if user:
            hist = self.env['lead.quality.history'].sudo().search_read(
                [('lead_id', 'in', leads.ids), ('user_id', '=', user.id)],
                ['lead_id', 'lead_quality', 'change_date'], order='change_date asc')
            for h in hist:
                last_quality[h['lead_id'][0]] = {
                    'quality': h['lead_quality'],
                    'date': h['change_date'],
                }

        quality_labels = dict(Lead._fields['lead_quality'].selection)

        rows = []
        for lead in leads:
            lq = last_quality.get(lead.id)
            lc = last_call.get(lead.id)
            phone = lead.phone_number or ''
            masked_phone = ('XXXXXX' + phone[-4:]) if len(phone) >= 10 else (phone or '')
            rows.append({
                'lead_id': lead.id,
                'name': lead.name,
                'phone': masked_phone,
                'current_quality': quality_labels.get(lead.lead_quality, lead.lead_quality or '—'),
                'quality_set_by_officer': (
                    quality_labels.get(lq['quality'], lq['quality']) if lq else '—'),
                'quality_changed_on': (
                    fields.Datetime.to_string(lq['date']) if lq else ''),
                'last_called_on': (
                    fields.Datetime.to_string(lc['call_time']) if lc else ''),
                'call_status': lc['call_status'] if lc else '',
                'admission_status': bool(lead.admission_status),
                'admission_date': (
                    fields.Datetime.to_string(lead.admission_date)
                    if lead.admission_date else ''),
            })

        # Most recently touched (by call or quality change) first
        rows.sort(
            key=lambda r: r['quality_changed_on'] or r['last_called_on'] or '',
            reverse=True)

        return {
            'employee_name': employee.name,
            'mode': mode,
            'total': len(rows),
            'admitted': sum(1 for r in rows if r['admission_status']),
            'rows': rows,
        }

    # ------------------------------------------------------------------
    # Flat rows for XLSX export (same visibility rules)
    # ------------------------------------------------------------------
    @api.model
    def get_call_report_export_rows(self, date_from=None, date_to=None):
        data = self.get_call_report(date_from, date_to)
        rows = []
        for team in data['teams']:
            for r in team['rows']:
                rows.append({
                    'team': team['name'],
                    'name': r['name'],
                    'role': 'Team Lead' if r['role'] == 'tl' else 'Admission Officer',
                    'tl_name': r['tl_name'],
                    'assigned': r['assigned'],
                    'calls': r['calls'],
                    'outgoing': r['outgoing'],
                    'incoming': r['incoming'],
                    'connected': r['connected'],
                    'not_connected': r['not_connected'],
                    'unique_leads': r['unique_leads'],
                    'pending': r['pending'],
                    'duration': r['duration'],
                    'avg_duration': r['avg_duration'],
                })
        for r in data['others']:
            rows.append({
                'team': 'No Team',
                'name': r['name'],
                'role': 'Other',
                'tl_name': '',
                'assigned': r['assigned'],
                'calls': r['calls'],
                'outgoing': r['outgoing'],
                'incoming': r['incoming'],
                'connected': r['connected'],
                'not_connected': r['not_connected'],
                'unique_leads': r['unique_leads'],
                'pending': r['pending'],
                'duration': r['duration'],
                'avg_duration': r['avg_duration'],
            })
        return data, rows
