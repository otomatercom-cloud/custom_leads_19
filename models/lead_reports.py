# -*- coding: utf-8 -*-
"""Lead Reports engine: ~40 reports behind one RPC (otm.lead.reports.run).
Every report returns {title, note, columns, rows, totals, chart}. All reads use the ORM, so the
user's record rules apply (officers only see their own leads)."""
from collections import defaultdict
from datetime import timedelta

import pytz

from odoo import api, fields, models, _

from .call_report import _fmt_duration, _is_connected, _parse_duration_seconds

LIMIT_CALLS = 150000

CATALOG = [
    ('Lead intake', [
        ('intake_source', 'Leads by source', 'Leads, assigned, called, admissions and conversion per lead source'),
        ('intake_campaign', 'Leads by campaign', 'Same numbers per source campaign'),
        ('intake_trend', 'Lead intake trend', 'New leads and admissions per day / week / month'),
        ('reenquiry', 'Re-attempt requests', 'Re-attempt (re-enquiry) requests by current lead owner'),
        ('import_logs', 'Odoo 17 import logs', 'Every import run with created, skipped and failed counts'),
    ]),
    ('Speed and response', [
        ('speed_officer', 'Response speed by officer', 'Average time to assign and time to first call'),
        ('not_called_aging', 'Not called yet - aging', 'Leads never called, by how long they have waited'),
        ('not_assigned', 'Not assigned leads', 'Leads still waiting for an officer'),
    ]),
    ('Admission officers', [
        ('officer_scorecard', 'Officer scorecard', 'Leads, calls, talk time, follow-ups, admissions per officer'),
        ('call_target', 'Daily call target vs actual', 'Calls per officer per day against the daily goal'),
        ('idle_officers', 'Idle officers', 'Team members with no calls in the period'),
        ('attendance_calls', 'Attendance vs calls', 'Days present against calls made'),
    ]),
    ('Teams', [
        ('team_compare', 'Team comparison', 'Leads, calls, talk time, admissions and speed per team'),
    ]),
    ('Pipeline and quality', [
        ('stage_funnel', 'Stage funnel', 'Leads per stage category'),
        ('quality_dist', 'Lead quality distribution', 'Hot, Warm, Cold, RNR and every other quality'),
        ('quality_changes', 'Quality changes', 'How many quality changes happened, by new quality and by user'),
        ('rnr_leads', 'RNR leads', 'Ringing Not Responding leads with call count and last call'),
        ('call_aging', 'Days since last call', 'Open leads by days since the last call'),
    ]),
    ('Follow-ups', [
        ('followup_officer', 'Follow-ups by officer', 'Scheduled, done, cancelled and overdue per officer'),
        ('followup_upcoming', "Today's and tomorrow's follow-ups", 'Scheduled follow-ups for today and tomorrow'),
        ('followup_missed', 'Missed follow-ups', 'Scheduled follow-ups whose time has passed'),
    ]),
    ('Counselling and admissions', [
        ('counselling_summary', 'Counselling summary', 'Sessions by counsellor, status and outcome'),
        ('conv_officer', 'Conversion by officer', 'Leads to admissions per admission officer'),
        ('conv_course', 'Admissions by course', 'Admissions, fee and conversion per course'),
        ('course_demand', 'Course demand', 'Course interested vs admitted'),
        ('lost_reasons', 'Lost and not interested', 'Lost reasons and not-interested counts'),
    ]),
    ('Assignment and pool', [
        ('assignment_history', 'Assignment history', 'Every assignment / reassignment in the period'),
        ('auto_reassigned', 'Auto-reassigned leads', 'Leads moved automatically by the pool rules'),
        ('pool_fairness', 'Pool fairness', 'Leads handed to each officer in the period'),
    ]),
    ('Call details and duration', [
        ('call_log_detail', 'Call log detail', 'Every call with agent, status, duration and recording'),
        ('call_officer', 'Call duration by officer', 'Calls, talk time, average and longest call'),
        ('call_lead', 'Call duration by lead', 'Top 50 leads by talk time'),
        ('connected_split', 'Connected vs not connected', 'Answered and missed calls by officer and by source'),
        ('call_heatmap', 'Peak call hours', 'Calls by weekday and hour'),
        ('short_calls', 'Short calls (under 30 s)', 'Connected calls shorter than 30 seconds'),
        ('calls_by_quality', 'Calls per lead by quality', 'Average calls and talk time per lead quality'),
        ('recording_coverage', 'Recording coverage', 'Calls with and without a recording'),
        ('in_out_split', 'Incoming vs outgoing', 'Call direction per officer'),
    ]),
    ('Management', [
        ('weekly_summary', 'Weekly summary', 'Leads, calls, talk time, admissions and speed per week'),
    ]),
]


def _col(key, label, typ='text'):
    return {'key': key, 'label': label, 'type': typ}


class OtmLeadReports(models.AbstractModel):
    _name = 'otm.lead.reports'
    _description = 'Lead Reports engine'

    # ───────────────────────── public api ──────────────────────────
    @api.model
    def get_catalog(self):
        return [{'group': g, 'reports': [{'id': i, 'title': t, 'desc': d} for i, t, d in rs]} for g, rs in CATALOG]

    @api.model
    def get_options(self):
        L = self.env['leads.logic']
        return {
            'sources': [{'id': s.id, 'name': s.name} for s in self.env['leads.sources'].sudo().search([])],
            'teams': [{'id': t.id, 'name': t.name} for t in self.env['lead.team'].sudo().search([])],
            'owners': L.get_response_dashboard_options()['owners'],
            'courses': [{'id': c.id, 'name': c.display_name} for c in self.env['course.interested'].sudo().search([])],
        }

    @api.model
    def run(self, report_id, filters=None):
        f = dict(filters or {})
        self = self.with_context(tz=self.env['leads.logic']._rd_tzname())
        fn = getattr(self, '_r_%s' % report_id, None)
        if not fn:
            return {'error': _('Unknown report')}
        res = fn(f)
        res.setdefault('note', '')
        res.setdefault('totals', {})
        res.setdefault('chart', False)
        res['title'] = next((t for g, rs in CATALOG for i, t, d in rs if i == report_id), report_id)
        res['count'] = len(res.get('rows', []))
        return res

    # ───────────────────────── helpers ─────────────────────────────
    def _bounds(self, f):
        L = self.env['leads.logic']
        today = fields.Date.context_today(self)
        d1 = f.get('date_from') or str(today - timedelta(days=29))
        d2 = f.get('date_to') or str(today)
        return L._rd_utc(d1), L._rd_utc(d2, end=True)

    def _lf(self, f, prefix='', skip_owner=False):
        """Filter terms (source / team / officer / course) on leads.logic, optionally prefixed."""
        p = prefix
        dom = []
        if f.get('source'):
            dom.append((p + 'leads_source', '=', int(f['source'])))
        if f.get('team'):
            dom.append((p + 'team_id', '=', int(f['team'])))
        if f.get('owner') and not skip_owner:
            dom.append((p + 'lead_owner', '=', int(f['owner'])))
        if f.get('course'):
            dom.append((p + 'course_inter', 'in', [int(f['course'])]))
        return dom

    def _ldom(self, f, datefield='create_date'):
        s, e = self._bounds(f)
        return [(datefield, '>=', s), (datefield, '<', e)] + self._lf(f)

    def _user_of(self, f):
        if f.get('owner'):
            return self.env['hr.employee'].sudo().browse(int(f['owner'])).user_id
        return self.env['res.users']

    def _cdom(self, f):
        s, e = self._bounds(f)
        dom = [('call_time', '>=', s), ('call_time', '<', e)] + self._lf(f, 'lead_id.', skip_owner=True)
        u = self._user_of(f)
        if f.get('owner'):
            dom.append(('user_id', '=', u.id or 0))
        return dom

    def _calls(self, f, extra=()):
        rows = self.env['lead.call.log'].search_read(
            self._cdom(f) + list(extra),
            ['user_id', 'lead_id', 'call_time', 'call_status', 'duration', 'call_type', 'has_recording'],
            limit=LIMIT_CALLS, order='call_time asc')
        for r in rows:
            r['secs'] = _parse_duration_seconds(r.get('duration'))
            r['ok'] = _is_connected(r.get('call_status'), r['secs'])
        return rows

    def _sel(self, field):
        return dict(self.env['leads.logic']._fields[field].selection)

    @staticmethod
    def _pct(a, b):
        return round(a * 100.0 / b, 1) if b else 0.0

    def _grp(self, model, dom, field, extra_aggs=()):
        """-> {key: (record_or_value, count, *aggs)} for one groupby field."""
        out = {}
        for r in self.env[model]._read_group(dom, [field], ['__count'] + list(extra_aggs)):
            out[r[0].id if hasattr(r[0], 'id') else r[0]] = r
        return out

    @staticmethod
    def _name(rec, blank='(none)'):
        if hasattr(rec, '_name'):
            return rec.sudo().display_name if rec else blank
        return rec or blank

    def _tot(self, rows, keys):
        return {k: sum((r.get(k) or 0) for r in rows) for k in keys}

    def _bar(self, x, ys, kind='bar'):
        return {'kind': kind, 'x': x, 'ys': [{'key': k, 'label': l} for k, l in ys]}

    def _emp_user(self, emp_ids):
        emps = self.env['hr.employee'].sudo().browse([i for i in emp_ids if i])
        return {e.id: e.user_id.id for e in emps}

    # ═══════════════════ 1. LEAD INTAKE ═══════════════════════════
    def _by_field(self, f, field, label):
        dom = self._ldom(f)
        L = self.env['leads.logic']
        tot = self._grp('leads.logic', dom, field)
        asg = self._grp('leads.logic', dom + [('first_assigned_dt', '!=', False)], field)
        cal = self._grp('leads.logic', dom + [('first_called_dt', '!=', False)], field)
        adm = self._grp('leads.logic', dom + [('admission_status', '=', True)], field)
        rows = []
        for k, r in tot.items():
            n = r[1]
            rows.append({'name': self._name(r[0]), 'leads': n,
                         'assigned': asg.get(k, (0, 0))[1], 'called': cal.get(k, (0, 0))[1],
                         'admissions': adm.get(k, (0, 0))[1], 'conv': self._pct(adm.get(k, (0, 0))[1], n)})
        rows.sort(key=lambda x: -x['leads'])
        return {'columns': [_col('name', label), _col('leads', 'Leads', 'int'), _col('assigned', 'Assigned', 'int'),
                            _col('called', 'Called', 'int'), _col('admissions', 'Admissions', 'int'),
                            _col('conv', 'Conversion %', 'pct')],
                'rows': rows, 'totals': self._tot(rows, ['leads', 'assigned', 'called', 'admissions']),
                'chart': self._bar('name', [('leads', 'Leads'), ('admissions', 'Admissions')])}

    def _r_intake_source(self, f):
        return self._by_field(f, 'leads_source', 'Lead source')

    def _r_intake_campaign(self, f):
        return self._by_field(f, 'source_campaign_id', 'Source campaign')

    def _r_intake_trend(self, f):
        g = f.get('group') if f.get('group') in ('day', 'week', 'month') else 'day'
        dom = self._ldom(f)
        gb = 'create_date:%s' % g
        fmt = {'day': '%d %b %Y', 'week': 'Wk %d %b', 'month': '%b %Y'}[g]
        data = defaultdict(lambda: {'leads': 0, 'admissions': 0})
        for k, c in self.env['leads.logic']._read_group(dom, [gb], ['__count']):
            data[k]['leads'] = c
        for k, c in self.env['leads.logic']._read_group(dom + [('admission_status', '=', True)], [gb], ['__count']):
            data[k]['admissions'] = c
        rows = [{'name': k.strftime(fmt) if k else '-', 'leads': v['leads'], 'admissions': v['admissions']}
                for k, v in sorted(data.items(), key=lambda x: str(x[0]))]
        return {'columns': [_col('name', 'Period'), _col('leads', 'Leads', 'int'), _col('admissions', 'Admissions', 'int')],
                'rows': rows, 'totals': self._tot(rows, ['leads', 'admissions']),
                'chart': self._bar('name', [('leads', 'Leads'), ('admissions', 'Admissions')], 'line')}

    def _r_reenquiry(self, f):
        s, e = self._bounds(f)
        grp = self._grp('otomater.lead.reattempt', [('request_date', '>=', s), ('request_date', '<', e)],
                        'existing_owner_id')
        rows = sorted(({'name': self._name(r[0]), 'requests': r[1]} for r in grp.values()), key=lambda x: -x['requests'])
        return {'columns': [_col('name', 'Current lead owner'), _col('requests', 'Re-attempt requests', 'int')],
                'rows': rows, 'totals': self._tot(rows, ['requests']),
                'chart': self._bar('name', [('requests', 'Requests')])}

    def _r_import_logs(self, f):
        s, e = self._bounds(f)
        recs = self.env['otm.leads.odoo17.import.log'].search(
            [('create_date', '>=', s), ('create_date', '<', e)], order='id desc', limit=200)
        rows = [{'name': r.name, 'from': str(r.date_from or ''), 'to': str(r.date_to or ''), 'fetched': r.fetched_count,
                 'created': r.created_count, 'already': r.already_count, 'dup': r.duplicate_count,
                 'failed': r.failed_count, 'state': dict(r._fields['state'].selection).get(r.state, r.state)}
                for r in recs]
        return {'columns': [_col('name', 'Import'), _col('from', 'From'), _col('to', 'To'), _col('fetched', 'Selected', 'int'),
                            _col('created', 'Created', 'int'), _col('already', 'Already imported', 'int'),
                            _col('dup', 'Phone duplicates', 'int'), _col('failed', 'Failed', 'int'), _col('state', 'State')],
                'rows': rows, 'totals': self._tot(rows, ['fetched', 'created', 'already', 'dup', 'failed'])}

    # ═══════════════════ 2. SPEED ═════════════════════════════════
    def _r_speed_officer(self, f):
        L = self.env['leads.logic']
        raw = L._rd_breakdown(self._ldom(f), 'lead_owner')
        rows = [{'name': r['name'], 'leads': r['leads'], 'assign': r['assign'], 'call': r['call'],
                 'called': r['called'], 'not_called': r['not_called'], 'fast': r['fast_pct']} for r in raw]
        return {'columns': [_col('name', 'Admission officer'), _col('leads', 'Leads', 'int'), _col('assign', 'Avg time to assign', 'hrs'),
                            _col('call', 'Avg time to first call', 'hrs'), _col('called', 'Called', 'int'),
                            _col('not_called', 'Not called', 'int'), _col('fast', 'Called within 1h %', 'pct')],
                'rows': rows, 'totals': self._tot(rows, ['leads', 'called', 'not_called']),
                'chart': self._bar('name', [('assign', 'Assign (h)'), ('call', 'Call (h)')])}

    def _r_not_called_aging(self, f):
        now = fields.Datetime.now()
        recs = self.env['leads.logic'].search_read(
            self._ldom(f) + [('first_called_dt', '=', False), ('state', '!=', 'lost')], ['lead_owner', 'create_date'], limit=50000)
        buckets = [('Under 1 hour', 1), ('1 - 4 hours', 4), ('4 - 24 hours', 24), ('1 - 3 days', 72), ('Over 3 days', 10 ** 9)]
        per = defaultdict(lambda: [0] * 5)
        for r in recs:
            h = (now - r['create_date']).total_seconds() / 3600
            i = next(i for i, (_n, lim) in enumerate(buckets) if h < lim)
            per[r['lead_owner'][1] if r['lead_owner'] else '(not assigned)'][i] += 1
        rows = []
        for name, v in sorted(per.items(), key=lambda x: -sum(x[1])):
            rows.append(dict({'name': name, 'total': sum(v)}, **{'b%d' % i: n for i, n in enumerate(v)}))
        cols = [_col('name', 'Admission officer'), _col('total', 'Not called', 'int')] + \
               [_col('b%d' % i, b[0], 'int') for i, b in enumerate(buckets)]
        return {'columns': cols, 'rows': rows, 'totals': self._tot(rows, ['total'] + ['b%d' % i for i in range(5)]),
                'chart': self._bar('name', [('total', 'Not called')])}

    def _r_not_assigned(self, f):
        now = fields.Datetime.now()
        recs = self.env['leads.logic'].search(self._ldom(f) + [('lead_owner', '=', False), ('state', '!=', 'lost')],
                                              order='create_date asc', limit=300)
        rows = [{'ref': r.reference_no or '', 'name': r.name or '', 'source': r.leads_source.display_name or '',
                 'created': r.create_date, 'wait': (now - r.create_date).total_seconds() / 3600} for r in recs]
        return {'columns': [_col('ref', 'Reference'), _col('name', 'Lead'), _col('source', 'Lead source'),
                            _col('created', 'Created', 'dt'), _col('wait', 'Waiting', 'hrs')],
                'rows': rows, 'note': 'Oldest 300 leads waiting for an officer.'}

    # ═══════════════════ 3. OFFICERS ══════════════════════════════
    def _officer_stats(self, f):
        """-> dict key=(employee id) with every officer metric."""
        s, e = self._bounds(f)
        dom = self._ldom(f)
        tot = self._grp('leads.logic', dom, 'lead_owner')
        adm = self._grp('leads.logic', dom + [('admission_status', '=', True)], 'lead_owner')
        emp_user = self._emp_user(list(tot) + list(adm))
        user_emp = {u: eid for eid, u in emp_user.items() if u}
        stats = {}

        def st(eid, name):
            return stats.setdefault(eid, {'name': name, 'leads': 0, 'calls': 0, 'connected': 0, 'secs': 0,
                                           'longest': 0, 'fdone': 0, 'fsched': 0, 'fover': 0, 'adm': 0})
        for k, r in tot.items():
            st(k, self._name(r[0]))['leads'] = r[1]
        for k, r in adm.items():
            st(k, self._name(r[0]))['adm'] = r[1]
        users = self.env['res.users'].sudo()
        for c in self._calls(f):
            uid = c['user_id'][0] if c['user_id'] else 0
            eid = user_emp.get(uid, -uid)
            x = st(eid, c['user_id'][1] if c['user_id'] else '(no agent)')
            x['calls'] += 1
            x['secs'] += c['secs']
            x['longest'] = max(x['longest'], c['secs'])
            x['connected'] += 1 if c['ok'] else 0
        now = fields.Datetime.now()
        fdom = [('next_followup_date', '>=', s), ('next_followup_date', '<', e)] + self._lf(f, 'lead_id.', skip_owner=True)
        if f.get('owner'):
            fdom.append(('user_id', '=', self._user_of(f).id or 0))
        for fu in self.env['lead.followup'].search_read(fdom, ['user_id', 'status', 'next_followup_date'], limit=100000):
            uid = fu['user_id'][0] if fu['user_id'] else 0
            eid = user_emp.get(uid, -uid)
            x = st(eid, fu['user_id'][1] if fu['user_id'] else '(none)')
            if fu['status'] == 'done':
                x['fdone'] += 1
            elif fu['status'] == 'scheduled':
                x['fsched'] += 1
                if fu['next_followup_date'] and fu['next_followup_date'] <= now:
                    x['fover'] += 1
        return stats

    def _r_officer_scorecard(self, f):
        rows = []
        for x in self._officer_stats(f).values():
            rows.append({'name': x['name'], 'leads': x['leads'], 'calls': x['calls'], 'connected': x['connected'],
                         'conn': self._pct(x['connected'], x['calls']), 'secs': x['secs'],
                         'avg': (x['secs'] / x['calls']) if x['calls'] else 0, 'fdone': x['fdone'], 'fover': x['fover'],
                         'adm': x['adm'], 'conv': self._pct(x['adm'], x['leads'])})
        rows.sort(key=lambda r: -r['calls'])
        return {'columns': [_col('name', 'Admission officer'), _col('leads', 'Leads', 'int'), _col('calls', 'Calls', 'int'),
                            _col('connected', 'Connected', 'int'), _col('conn', 'Connected %', 'pct'),
                            _col('secs', 'Talk time', 'secs'), _col('avg', 'Avg call', 'secs'),
                            _col('fdone', 'Follow-ups done', 'int'), _col('fover', 'Follow-ups overdue', 'int'),
                            _col('adm', 'Admissions', 'int'), _col('conv', 'Conversion %', 'pct')],
                'rows': rows, 'totals': self._tot(rows, ['leads', 'calls', 'connected', 'secs', 'fdone', 'fover', 'adm']),
                'chart': self._bar('name', [('calls', 'Calls'), ('connected', 'Connected')])}

    def _r_call_target(self, f):
        goal = int(self.env['ir.config_parameter'].sudo().get_param('custom_leads_19.daily_call_goal') or 0)
        per = defaultdict(lambda: defaultdict(int))
        tz = pytz.timezone(self.env['leads.logic']._rd_tzname())
        for c in self._calls(f):
            day = pytz.utc.localize(c['call_time']).astimezone(tz).date()
            per[(c['user_id'][1] if c['user_id'] else '(none)', day)]['n'] += 1
        rows = [{'name': n, 'day': str(d), 'calls': v['n'], 'goal': goal, 'pct': self._pct(v['n'], goal),
                 'met': 'Yes' if goal and v['n'] >= goal else ('No' if goal else '-')}
                for (n, d), v in sorted(per.items(), key=lambda x: (x[0][1], x[0][0]), reverse=True)]
        return {'columns': [_col('day', 'Date'), _col('name', 'Officer'), _col('calls', 'Calls', 'int'),
                            _col('goal', 'Daily goal', 'int'), _col('pct', 'Achieved %', 'pct'), _col('met', 'Goal met')],
                'rows': rows, 'note': 'Daily goal: %s calls (Settings > Daily call goal).' % goal}

    def _members(self, f):
        dom = []
        if f.get('team'):
            dom.append(('team_id', '=', int(f['team'])))
        if f.get('owner'):
            dom.append(('employee_id', '=', int(f['owner'])))
        return self.env['lead.team.member'].sudo().search(dom)

    def _r_idle_officers(self, f):
        calls = defaultdict(int)
        for c in self._calls(dict(f, owner=False)):
            if c['user_id']:
                calls[c['user_id'][0]] += 1
        rows = []
        for m in self._members(f):
            u = m.employee_id.user_id
            if u and not calls.get(u.id):
                rows.append({'name': m.employee_id.name, 'team': m.team_id.name, 'calls': 0})
        return {'columns': [_col('name', 'Admission officer'), _col('team', 'Team'), _col('calls', 'Calls', 'int')],
                'rows': rows, 'note': 'Team members with no calls in the selected dates.'}

    def _r_attendance_calls(self, f):
        if 'hr.attendance' not in self.env:
            return {'columns': [_col('name', 'Officer')], 'rows': [], 'note': 'hr_attendance is not installed.'}
        s, e = self._bounds(f)
        tz = pytz.timezone(self.env['leads.logic']._rd_tzname())
        calls = defaultdict(int)
        for c in self._calls(dict(f, owner=False)):
            if c['user_id']:
                calls[c['user_id'][0]] += 1
        rows = []
        for m in self._members(f):
            emp = m.employee_id
            att = self.env['hr.attendance'].sudo().search([('employee_id', '=', emp.id), ('check_in', '>=', s), ('check_in', '<', e)])
            days = {pytz.utc.localize(a.check_in).astimezone(tz).date() for a in att}
            hrs = sum(a.worked_hours or 0 for a in att)
            n = calls.get(emp.user_id.id, 0)
            rows.append({'name': emp.name, 'days': len(days), 'hours': hrs, 'calls': n,
                         'per_day': round(n / len(days), 1) if days else 0, 'per_hour': round(n / hrs, 1) if hrs else 0})
        rows.sort(key=lambda r: -r['calls'])
        return {'columns': [_col('name', 'Admission officer'), _col('days', 'Days present', 'int'),
                            _col('hours', 'Hours worked', 'hrs'), _col('calls', 'Calls', 'int'),
                            _col('per_day', 'Calls per day', 'num'), _col('per_hour', 'Calls per hour', 'num')],
                'rows': rows, 'totals': self._tot(rows, ['days', 'calls'])}

    # ═══════════════════ 4. TEAMS ═════════════════════════════════
    def _r_team_compare(self, f):
        dom = self._ldom(f)
        L = self.env['leads.logic']
        base = {r['id']: r for r in L._rd_breakdown(dom, 'team_id')}
        adm = self._grp('leads.logic', dom + [('admission_status', '=', True)], 'team_id')
        calls = defaultdict(lambda: {'n': 0, 'ok': 0, 'secs': 0})
        lead_team = {}
        for c in self._calls(f):
            lid = c['lead_id'][0] if c['lead_id'] else 0
            lead_team.setdefault(lid, None)
        if lead_team:
            for r in L.browse(list(lead_team)).read(['team_id']):
                lead_team[r['id']] = r['team_id'][0] if r['team_id'] else 0
        for c in self._calls(f):
            k = lead_team.get(c['lead_id'][0] if c['lead_id'] else 0, 0)
            x = calls[k]
            x['n'] += 1
            x['ok'] += 1 if c['ok'] else 0
            x['secs'] += c['secs']
        rows = []
        for k, r in base.items():
            c = calls.get(k, {'n': 0, 'ok': 0, 'secs': 0})
            a = adm.get(k, (0, 0))[1]
            rows.append({'name': r['name'], 'leads': r['leads'], 'calls': c['n'], 'ok': c['ok'], 'secs': c['secs'],
                         'adm': a, 'conv': self._pct(a, r['leads']), 'assign': r['assign'], 'call': r['call']})
        rows.sort(key=lambda r: -r['leads'])
        return {'columns': [_col('name', 'Team'), _col('leads', 'Leads', 'int'), _col('calls', 'Calls', 'int'),
                            _col('ok', 'Connected', 'int'), _col('secs', 'Talk time', 'secs'), _col('adm', 'Admissions', 'int'),
                            _col('conv', 'Conversion %', 'pct'), _col('assign', 'Avg assign', 'hrs'), _col('call', 'Avg first call', 'hrs')],
                'rows': rows, 'totals': self._tot(rows, ['leads', 'calls', 'ok', 'secs', 'adm']),
                'chart': self._bar('name', [('leads', 'Leads'), ('calls', 'Calls'), ('adm', 'Admissions')])}

    # ═══════════════════ 5. PIPELINE ══════════════════════════════
    def _r_stage_funnel(self, f):
        labels = self._sel('lead_stage_category')
        g = self._grp('leads.logic', self._ldom(f), 'lead_stage_category')
        rows = [{'name': labels.get(k, k or '(none)'), 'leads': r[1]} for k, r in g.items()]
        rows.sort(key=lambda r: -r['leads'])
        n = sum(r['leads'] for r in rows)
        for r in rows:
            r['share'] = self._pct(r['leads'], n)
        return {'columns': [_col('name', 'Stage'), _col('leads', 'Leads', 'int'), _col('share', 'Share %', 'pct')],
                'rows': rows, 'totals': self._tot(rows, ['leads']), 'chart': self._bar('name', [('leads', 'Leads')])}

    def _r_quality_dist(self, f):
        labels = self._sel('lead_quality')
        g = self._grp('leads.logic', self._ldom(f), 'lead_quality')
        rows = [{'name': labels.get(k, k or '(not set)'), 'leads': r[1]} for k, r in g.items()]
        rows.sort(key=lambda r: -r['leads'])
        n = sum(r['leads'] for r in rows)
        for r in rows:
            r['share'] = self._pct(r['leads'], n)
        return {'columns': [_col('name', 'Lead quality'), _col('leads', 'Leads', 'int'), _col('share', 'Share %', 'pct')],
                'rows': rows, 'totals': self._tot(rows, ['leads']), 'chart': self._bar('name', [('leads', 'Leads')])}

    def _r_quality_changes(self, f):
        s, e = self._bounds(f)
        labels = self._sel('lead_quality')
        dom = [('change_date', '>=', s), ('change_date', '<', e)] + self._lf(f, 'lead_id.')
        H = self.env['lead.quality.history']
        rows = []
        for r in H._read_group(dom, ['lead_quality'], ['__count']):
            rows.append({'name': 'To: ' + labels.get(r[0], r[0] or '-'), 'changes': r[1]})
        rows.sort(key=lambda r: -r['changes'])
        by_user = [{'name': 'By: ' + self._name(r[0]), 'changes': r[1]}
                   for r in H._read_group(dom, ['user_id'], ['__count'])]
        by_user.sort(key=lambda r: -r['changes'])
        rows += by_user
        return {'columns': [_col('name', 'Change'), _col('changes', 'Changes', 'int')], 'rows': rows}

    def _r_rnr_leads(self, f):
        recs = self.env['leads.logic'].search(self._ldom(f) + [('lead_quality', '=', 'not_responding')],
                                              order='call_count desc, id desc', limit=300)
        last = {r[0].id: r[1] for r in self.env['lead.call.log']._read_group(
            [('lead_id', 'in', recs.ids)], ['lead_id'], ['call_time:max'])} if recs else {}
        rows = [{'ref': r.reference_no or '', 'name': r.name or '', 'owner': r.lead_owner.name or '',
                 'calls': r.call_count, 'last': last.get(r.id), 'created': r.create_date} for r in recs]
        return {'columns': [_col('ref', 'Reference'), _col('name', 'Lead'), _col('owner', 'Officer'), _col('calls', 'Calls', 'int'),
                            _col('last', 'Last call', 'dt'), _col('created', 'Created', 'dt')],
                'rows': rows, 'note': 'Top 300 by number of calls.'}

    def _r_call_aging(self, f):
        recs = self.env['leads.logic'].search(self._ldom(f) + [('state', 'not in', ['lost', 'qualified'])], limit=30000)
        last = {r[0].id: r[1] for r in self.env['lead.call.log']._read_group(
            [('lead_id', 'in', recs.ids)], ['lead_id'], ['call_time:max'])} if recs else {}
        now = fields.Datetime.now()
        buckets = [('Called today', 1), ('1 - 2 days', 3), ('3 - 7 days', 8), ('8 - 15 days', 16), ('Over 15 days', 10 ** 6)]
        cnt = defaultdict(int)
        for r in recs:
            lc = last.get(r.id)
            if not lc:
                cnt['Never called'] += 1
                continue
            d = (now - lc).days
            cnt[next(n for n, lim in buckets if d < lim)] += 1
        order = ['Never called'] + [b[0] for b in buckets]
        rows = [{'name': n, 'leads': cnt.get(n, 0)} for n in order]
        return {'columns': [_col('name', 'Last call'), _col('leads', 'Open leads', 'int')], 'rows': rows,
                'totals': self._tot(rows, ['leads']), 'chart': self._bar('name', [('leads', 'Leads')])}

    # ═══════════════════ 6. FOLLOW-UPS ════════════════════════════
    def _fdom(self, f, ranged=True):
        dom = self._lf(f, 'lead_id.', skip_owner=True)
        if ranged:
            s, e = self._bounds(f)
            dom += [('next_followup_date', '>=', s), ('next_followup_date', '<', e)]
        if f.get('owner'):
            dom.append(('user_id', '=', self._user_of(f).id or 0))
        return dom

    def _r_followup_officer(self, f):
        now = fields.Datetime.now()
        per = defaultdict(lambda: {'scheduled': 0, 'done': 0, 'cancelled': 0, 'overdue': 0})
        for fu in self.env['lead.followup'].search_read(self._fdom(f), ['user_id', 'status', 'next_followup_date'], limit=100000):
            x = per[fu['user_id'][1] if fu['user_id'] else '(none)']
            x[fu['status']] += 1
            if fu['status'] == 'scheduled' and fu['next_followup_date'] <= now:
                x['overdue'] += 1
        rows = [dict({'name': n}, **v, total=sum(v[k] for k in ('scheduled', 'done', 'cancelled'))) for n, v in per.items()]
        rows.sort(key=lambda r: -r['total'])
        return {'columns': [_col('name', 'Follow-up by'), _col('total', 'Total', 'int'), _col('done', 'Done', 'int'),
                            _col('scheduled', 'Scheduled', 'int'), _col('overdue', 'Overdue', 'int'), _col('cancelled', 'Cancelled', 'int')],
                'rows': rows, 'totals': self._tot(rows, ['total', 'done', 'scheduled', 'overdue', 'cancelled']),
                'chart': self._bar('name', [('done', 'Done'), ('overdue', 'Overdue')])}

    def _fu_rows(self, recs):
        return [{'when': r.next_followup_date, 'lead': r.lead_id.name or '', 'ref': r.lead_id.reference_no or '',
                 'by': r.user_id.name or '', 'remarks': (r.remarks or '')[:120]} for r in recs]

    _FU_COLS = [_col('when', 'Follow-up time', 'dt'), _col('ref', 'Reference'), _col('lead', 'Lead'),
                _col('by', 'Follow-up by'), _col('remarks', 'Remarks')]

    def _r_followup_upcoming(self, f):
        L = self.env['leads.logic']
        today = fields.Date.context_today(self)
        recs = self.env['lead.followup'].search(
            self._fdom(f, ranged=False) + [('status', '=', 'scheduled'), ('next_followup_date', '>=', L._rd_utc(today)),
                                          ('next_followup_date', '<', L._rd_utc(today + timedelta(days=1), end=True))],
            order='next_followup_date asc', limit=500)
        return {'columns': self._FU_COLS, 'rows': self._fu_rows(recs)}

    def _r_followup_missed(self, f):
        recs = self.env['lead.followup'].search(
            self._fdom(f) + [('status', '=', 'scheduled'), ('next_followup_date', '<=', fields.Datetime.now())],
            order='next_followup_date asc', limit=500)
        return {'columns': self._FU_COLS, 'rows': self._fu_rows(recs), 'note': 'Oldest 500 missed follow-ups.'}

    # ═══════════════════ 7. COUNSELLING / ADMISSIONS ══════════════
    def _r_counselling_summary(self, f):
        s, e = self._bounds(f)
        dom = [('appointment_date', '>=', s), ('appointment_date', '<', e)] + self._lf(f, 'lead_id.', skip_owner=True)
        per = defaultdict(lambda: defaultdict(int))
        for r in self.env['lead.counselling']._read_group(dom, ['counsellor_id', 'state', 'outcome'], ['__count']):
            x = per[self._name(r[0])]
            x['total'] += r[3]
            x[r[1]] += r[3]
            if r[2] == 'admission_confirmed':
                x['confirmed'] += r[3]
        rows = [{'name': n, 'total': v['total'], 'done': v['done'], 'scheduled': v['scheduled'], 'noshow': v['no_show'],
                 'cancelled': v['cancelled'], 'confirmed': v['confirmed']} for n, v in per.items()]
        rows.sort(key=lambda r: -r['total'])
        return {'columns': [_col('name', 'Counsellor'), _col('total', 'Sessions', 'int'), _col('done', 'Done', 'int'),
                            _col('scheduled', 'Scheduled', 'int'), _col('noshow', 'No show', 'int'),
                            _col('cancelled', 'Cancelled', 'int'), _col('confirmed', 'Admission confirmed', 'int')],
                'rows': rows, 'totals': self._tot(rows, ['total', 'done', 'scheduled', 'noshow', 'cancelled', 'confirmed']),
                'chart': self._bar('name', [('done', 'Done'), ('confirmed', 'Admission confirmed')])}

    def _r_conv_officer(self, f):
        return self._by_field(f, 'lead_owner', 'Admission officer')

    def _r_conv_course(self, f):
        dom = self._ldom(f, 'admission_date') + [('admission_status', '=', True)]
        g = self.env['leads.logic']._read_group(dom, ['admission_course'], ['__count', 'admission_amount:sum'])
        rows = [{'name': r[0] or '(not set)', 'adm': r[1], 'fee': r[2] or 0} for r in g]
        rows.sort(key=lambda r: -r['adm'])
        return {'columns': [_col('name', 'Course'), _col('adm', 'Admissions', 'int'), _col('fee', 'Admission fee', 'num')],
                'rows': rows, 'totals': self._tot(rows, ['adm', 'fee']), 'chart': self._bar('name', [('adm', 'Admissions')]),
                'note': 'Admissions with an admission date in the period.'}

    def _r_course_demand(self, f):
        dom = self._ldom(f)
        L = self.env['leads.logic']
        tot = self._grp('leads.logic', dom, 'course_inter')
        adm = self._grp('leads.logic', dom + [('admission_status', '=', True)], 'course_inter')
        rows = [{'name': self._name(r[0], '(none)'), 'leads': r[1], 'adm': adm.get(k, (0, 0))[1],
                 'conv': self._pct(adm.get(k, (0, 0))[1], r[1])} for k, r in tot.items()]
        rows.sort(key=lambda r: -r['leads'])
        return {'columns': [_col('name', 'Course interested'), _col('leads', 'Leads', 'int'),
                            _col('adm', 'Admitted', 'int'), _col('conv', 'Conversion %', 'pct')],
                'rows': rows, 'totals': self._tot(rows, ['leads', 'adm']),
                'chart': self._bar('name', [('leads', 'Leads'), ('adm', 'Admitted')])}

    def _r_lost_reasons(self, f):
        dom = self._ldom(f)
        rows = []
        for r in self.env['leads.logic']._read_group(dom + [('state', '=', 'lost')], ['lost_reason'], ['__count']):
            rows.append({'name': 'Lost: ' + ((r[0] or '(no reason)').strip()[:80]), 'leads': r[1]})
        rows.sort(key=lambda r: -r['leads'])
        labels = self._sel('lead_quality')
        for q in ('not_interested', 'wrong_number', 'not_enquiry', 'joined_other_institute', 'bad_lead', 'crash_lead'):
            n = self.env['leads.logic'].search_count(dom + [('lead_quality', '=', q)])
            if n:
                rows.append({'name': 'Quality: ' + labels.get(q, q), 'leads': n})
        return {'columns': [_col('name', 'Reason'), _col('leads', 'Leads', 'int')], 'rows': rows,
                'totals': self._tot(rows, ['leads'])}

    # ═══════════════════ 8. ASSIGNMENT ════════════════════════════
    def _r_assignment_history(self, f):
        s, e = self._bounds(f)
        dom = [('assigned_date', '>=', s), ('assigned_date', '<', e)] + self._lf(f, 'lead_id.', skip_owner=True)
        if f.get('owner'):
            dom.append(('owner_id', '=', int(f['owner'])))
        recs = self.env['lead.assignment.history'].search(dom, order='assigned_date desc', limit=500)
        rows = [{'when': r.assigned_date, 'ref': r.lead_id.reference_no or '', 'lead': r.lead_id.name or '',
                 'owner': r.owner_id.name or '', 'by': r.assigned_by.name or ''} for r in recs]
        return {'columns': [_col('when', 'Assigned on', 'dt'), _col('ref', 'Reference'), _col('lead', 'Lead'),
                            _col('owner', 'Assigned to'), _col('by', 'Assigned by')],
                'rows': rows, 'note': 'Latest 500 assignments.'}

    def _r_auto_reassigned(self, f):
        g = self._grp('leads.logic', self._ldom(f) + [('auto_reassign_count', '>', 0)], 'lead_owner', ['auto_reassign_count:sum'])
        rows = [{'name': self._name(r[0]), 'leads': r[1], 'moves': r[2] or 0} for r in g.values()]
        rows.sort(key=lambda r: -r['moves'])
        return {'columns': [_col('name', 'Current officer'), _col('leads', 'Leads moved to them', 'int'),
                            _col('moves', 'Automatic moves', 'int')],
                'rows': rows, 'totals': self._tot(rows, ['leads', 'moves'])}

    def _r_pool_fairness(self, f):
        s, e = self._bounds(f)
        dom = [('assigned_date', '>=', s), ('assigned_date', '<', e)] + self._lf(f, 'lead_id.', skip_owner=True)
        g = self._grp('lead.assignment.history', dom, 'owner_id')
        rows = [{'name': self._name(r[0]), 'leads': r[1]} for r in g.values()]
        rows.sort(key=lambda r: -r['leads'])
        n = sum(r['leads'] for r in rows)
        avg = n / len(rows) if rows else 0
        for r in rows:
            r['vs'] = round(r['leads'] - avg, 1)
        return {'columns': [_col('name', 'Admission officer'), _col('leads', 'Leads received', 'int'),
                            _col('vs', 'Difference from average', 'num')],
                'rows': rows, 'totals': self._tot(rows, ['leads']), 'chart': self._bar('name', [('leads', 'Leads')])}

    # ═══════════════════ 9. CALLS ═════════════════════════════════
    def _r_call_log_detail(self, f):
        recs = self.env['lead.call.log'].search(self._cdom(f), order='call_time desc', limit=500)
        rows = [{'when': r.call_time, 'ref': r.lead_id.reference_no or '', 'lead': r.lead_id.name or '',
                 'agent': r.user_id.name or '', 'type': (r.call_type or '').title(), 'status': r.call_status or '',
                 'secs': _parse_duration_seconds(r.duration), 'rec': 'Yes' if r.has_recording else 'No'} for r in recs]
        return {'columns': [_col('when', 'Call time', 'dt'), _col('ref', 'Reference'), _col('lead', 'Lead'), _col('agent', 'Agent'),
                            _col('type', 'Type'), _col('status', 'Status'), _col('secs', 'Duration', 'secs'), _col('rec', 'Recording')],
                'rows': rows, 'totals': self._tot(rows, ['secs']), 'note': 'Latest 500 calls. Use Export for the same list.'}

    def _r_call_officer(self, f):
        per = {}
        days = defaultdict(set)
        tz = pytz.timezone(self.env['leads.logic']._rd_tzname())
        for c in self._calls(f):
            n = c['user_id'][1] if c['user_id'] else '(none)'
            x = per.setdefault(n, {'calls': 0, 'ok': 0, 'secs': 0, 'longest': 0})
            x['calls'] += 1
            x['ok'] += 1 if c['ok'] else 0
            x['secs'] += c['secs']
            x['longest'] = max(x['longest'], c['secs'])
            days[n].add(pytz.utc.localize(c['call_time']).astimezone(tz).date())
        rows = [{'name': n, 'calls': x['calls'], 'ok': x['ok'], 'secs': x['secs'],
                 'avg': x['secs'] / x['ok'] if x['ok'] else 0, 'longest': x['longest'],
                 'per_day': round(x['calls'] / len(days[n]), 1)} for n, x in per.items()]
        rows.sort(key=lambda r: -r['secs'])
        return {'columns': [_col('name', 'Agent'), _col('calls', 'Calls', 'int'), _col('ok', 'Connected', 'int'),
                            _col('secs', 'Total talk time', 'secs'), _col('avg', 'Avg connected call', 'secs'),
                            _col('longest', 'Longest call', 'secs'), _col('per_day', 'Calls per day', 'num')],
                'rows': rows, 'totals': self._tot(rows, ['calls', 'ok', 'secs']),
                'chart': self._bar('name', [('calls', 'Calls'), ('ok', 'Connected')])}

    def _r_call_lead(self, f):
        per = defaultdict(lambda: {'calls': 0, 'secs': 0, 'name': ''})
        for c in self._calls(f):
            if c['lead_id']:
                x = per[c['lead_id'][0]]
                x['calls'] += 1
                x['secs'] += c['secs']
                x['name'] = c['lead_id'][1]
        top = sorted(per.items(), key=lambda kv: -kv[1]['secs'])[:50]
        leads = {l.id: l for l in self.env['leads.logic'].browse([k for k, _v in top])}
        rows = [{'ref': leads[k].reference_no or '', 'name': v['name'], 'owner': leads[k].lead_owner.name or '',
                 'calls': v['calls'], 'secs': v['secs']} for k, v in top]
        return {'columns': [_col('ref', 'Reference'), _col('name', 'Lead'), _col('owner', 'Officer'),
                            _col('calls', 'Calls', 'int'), _col('secs', 'Total talk time', 'secs')],
                'rows': rows, 'totals': self._tot(rows, ['calls', 'secs'])}

    def _r_connected_split(self, f):
        calls = self._calls(f)
        src = {}
        ids = list({c['lead_id'][0] for c in calls if c['lead_id']})
        if ids:
            for r in self.env['leads.logic'].browse(ids).read(['leads_source']):
                src[r['id']] = r['leads_source'][1] if r['leads_source'] else '(none)'
        per = defaultdict(lambda: {'calls': 0, 'ok': 0})
        for c in calls:
            for key in ('Officer: ' + (c['user_id'][1] if c['user_id'] else '(none)'),
                        'Source: ' + src.get(c['lead_id'][0] if c['lead_id'] else 0, '(none)')):
                per[key]['calls'] += 1
                per[key]['ok'] += 1 if c['ok'] else 0
        rows = [{'name': k, 'calls': v['calls'], 'ok': v['ok'], 'miss': v['calls'] - v['ok'],
                 'rate': self._pct(v['ok'], v['calls'])} for k, v in per.items()]
        rows.sort(key=lambda r: (r['name'][:4] != 'Offi', -r['calls']))
        return {'columns': [_col('name', 'Group'), _col('calls', 'Calls', 'int'), _col('ok', 'Connected', 'int'),
                            _col('miss', 'Not connected', 'int'), _col('rate', 'Connected %', 'pct')], 'rows': rows}

    def _r_call_heatmap(self, f):
        tz = pytz.timezone(self.env['leads.logic']._rd_tzname())
        grid = defaultdict(lambda: [0] * 24)
        for c in self._calls(f):
            t = pytz.utc.localize(c['call_time']).astimezone(tz)
            grid[t.weekday()][t.hour] += 1
        names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        cols = [_col('name', 'Weekday')] + [_col('h%d' % h, '%02d' % h, 'int') for h in range(24)] + [_col('total', 'Total', 'int')]
        rows = []
        for i, n in enumerate(names):
            v = grid.get(i, [0] * 24)
            rows.append(dict({'name': n, 'total': sum(v)}, **{'h%d' % h: v[h] for h in range(24)}))
        return {'columns': cols, 'rows': rows, 'totals': self._tot(rows, ['total'] + ['h%d' % h for h in range(24)]),
                'heat': True, 'note': 'Columns are the hour of the day (24 h clock).'}

    def _r_short_calls(self, f):
        rows = [{'when': c['call_time'], 'agent': c['user_id'][1] if c['user_id'] else '',
                 'lead': c['lead_id'][1] if c['lead_id'] else '', 'secs': c['secs'], 'status': c['call_status'] or ''}
                for c in reversed(self._calls(f)) if c['ok'] and 0 < c['secs'] < 30][:500]
        return {'columns': [_col('when', 'Call time', 'dt'), _col('agent', 'Agent'), _col('lead', 'Lead'),
                            _col('secs', 'Duration', 'secs'), _col('status', 'Status')], 'rows': rows}

    def _r_calls_by_quality(self, f):
        labels = self._sel('lead_quality')
        g = self.env['leads.logic']._read_group(self._ldom(f), ['lead_quality'], ['__count', 'call_count:sum', 'total_call_seconds:sum'])
        rows = [{'name': labels.get(r[0], r[0] or '(not set)'), 'leads': r[1], 'calls': r[2] or 0,
                 'avg_calls': round((r[2] or 0) / r[1], 1) if r[1] else 0, 'avg_secs': (r[3] or 0) / r[1] if r[1] else 0}
                for r in g]
        rows.sort(key=lambda r: -r['leads'])
        return {'columns': [_col('name', 'Lead quality'), _col('leads', 'Leads', 'int'), _col('calls', 'Total calls', 'int'),
                            _col('avg_calls', 'Avg calls per lead', 'num'), _col('avg_secs', 'Avg talk time per lead', 'secs')],
                'rows': rows, 'totals': self._tot(rows, ['leads', 'calls']),
                'chart': self._bar('name', [('avg_calls', 'Avg calls')])}

    def _r_recording_coverage(self, f):
        per = defaultdict(lambda: {'calls': 0, 'rec': 0})
        for c in self._calls(f):
            x = per[c['user_id'][1] if c['user_id'] else '(none)']
            x['calls'] += 1
            x['rec'] += 1 if c['has_recording'] else 0
        rows = [{'name': n, 'calls': v['calls'], 'rec': v['rec'], 'norec': v['calls'] - v['rec'],
                 'pct': self._pct(v['rec'], v['calls'])} for n, v in per.items()]
        rows.sort(key=lambda r: -r['calls'])
        return {'columns': [_col('name', 'Agent'), _col('calls', 'Calls', 'int'), _col('rec', 'With recording', 'int'),
                            _col('norec', 'Without', 'int'), _col('pct', 'Coverage %', 'pct')],
                'rows': rows, 'totals': self._tot(rows, ['calls', 'rec', 'norec'])}

    def _r_in_out_split(self, f):
        per = defaultdict(lambda: {'incoming': 0, 'outgoing': 0, 'other': 0})
        for c in self._calls(f):
            per[c['user_id'][1] if c['user_id'] else '(none)'][c['call_type'] if c['call_type'] in ('incoming', 'outgoing') else 'other'] += 1
        rows = [dict({'name': n}, **v, total=sum(v.values())) for n, v in per.items()]
        rows.sort(key=lambda r: -r['total'])
        return {'columns': [_col('name', 'Agent'), _col('total', 'Calls', 'int'), _col('outgoing', 'Outgoing', 'int'),
                            _col('incoming', 'Incoming', 'int'), _col('other', 'Not set', 'int')],
                'rows': rows, 'totals': self._tot(rows, ['total', 'outgoing', 'incoming', 'other']),
                'chart': self._bar('name', [('outgoing', 'Outgoing'), ('incoming', 'Incoming')])}

    # ═══════════════════ 10. MANAGEMENT ═══════════════════════════
    def _r_weekly_summary(self, f):
        L = self.env['leads.logic']
        dom = self._ldom(f)
        data = defaultdict(lambda: {'leads': 0, 'adm': 0, 'calls': 0, 'secs': 0, 'assign': 0.0, 'call': 0.0})
        for k, c in L._read_group(dom, ['create_date:week'], ['__count']):
            data[k]['leads'] = c
        for k, c in L._read_group(dom + [('admission_status', '=', True)], ['create_date:week'], ['__count']):
            data[k]['adm'] = c
        for k, v in L._read_group(dom + [('first_assigned_dt', '!=', False)], ['create_date:week'], ['assign_delay_hrs:avg']):
            data[k]['assign'] = v or 0
        for k, v in L._read_group(dom + [('first_called_dt', '!=', False)], ['create_date:week'], ['call_delay_hrs:avg']):
            data[k]['call'] = v or 0
        calls = defaultdict(lambda: [0, 0])
        for c in self._calls(f):
            d = c['call_time'].date()
            wk = d - timedelta(days=d.weekday())
            calls[wk][0] += 1
            calls[wk][1] += c['secs']
        rows = []
        for k in sorted(set(data) | set(calls), key=str):
            kk = k.date() if hasattr(k, 'date') else k
            v = data.get(k, {'leads': 0, 'adm': 0, 'assign': 0, 'call': 0})
            cl = calls.get(kk, [0, 0])
            rows.append({'name': 'Week of %s' % kk.strftime('%d %b %Y'), 'leads': v['leads'], 'adm': v['adm'],
                         'conv': self._pct(v['adm'], v['leads']), 'calls': cl[0], 'secs': cl[1],
                         'assign': v['assign'], 'call': v['call']})
        return {'columns': [_col('name', 'Week'), _col('leads', 'New leads', 'int'), _col('adm', 'Admissions', 'int'),
                            _col('conv', 'Conversion %', 'pct'), _col('calls', 'Calls', 'int'), _col('secs', 'Talk time', 'secs'),
                            _col('assign', 'Avg assign', 'hrs'), _col('call', 'Avg first call', 'hrs')],
                'rows': rows, 'totals': self._tot(rows, ['leads', 'adm', 'calls', 'secs']),
                'chart': self._bar('name', [('leads', 'Leads'), ('calls', 'Calls')], 'line')}
