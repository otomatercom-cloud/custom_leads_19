# -*- coding: utf-8 -*-
"""Data provider for the Response Performance dashboard (assign delay / call delay,
daily-weekly-monthly-yearly averages, lead source / team / admission officer breakdowns).
All reads go through the ORM so record rules (officer sees own leads) always apply."""
import pytz
from datetime import datetime, timedelta

from odoo import api, fields, models

CALLED_FAST_HRS = 1.0  # a lead counts as "called fast" when first called within this many hours


class LeadsLogicResponseDashboard(models.Model):
    _inherit = 'leads.logic'

    # ── helpers ───────────────────────────────────────────────────────
    def _rd_tz(self):
        return pytz.timezone(self.env.user.tz or 'Asia/Kolkata')

    def _rd_utc(self, d, end=False):
        """Local date (str/date) -> naive UTC datetime at start (or end) of that day."""
        d = fields.Date.to_date(d)
        t = datetime(d.year, d.month, d.day) + (timedelta(days=1) if end else timedelta())
        return self._rd_tz().localize(t).astimezone(pytz.utc).replace(tzinfo=None)

    def _rd_avg(self, dom, field, ref):
        res = self._read_group(dom + [(ref, '!=', False)], [], ['%s:avg' % field])
        return (res[0][0] if res else 0.0) or 0.0

    def _rd_stats(self, dom):
        total = self.search_count(dom)
        assigned = self.search_count(dom + [('first_assigned_dt', '!=', False)])
        called = self.search_count(dom + [('first_called_dt', '!=', False)])
        fast = self.search_count(dom + [('first_called_dt', '!=', False),
                                        ('call_delay_hrs', '<=', CALLED_FAST_HRS)])
        return {
            'total': total, 'assigned': assigned, 'called': called,
            'not_assigned': total - assigned, 'not_called': total - called,
            'fast': fast,
            'fast_pct': round(fast * 100.0 / total, 1) if total else 0.0,
            'called_pct': round(called * 100.0 / total, 1) if total else 0.0,
            'avg_assign': self._rd_avg(dom, 'assign_delay_hrs', 'first_assigned_dt'),
            'avg_call': self._rd_avg(dom, 'call_delay_hrs', 'first_called_dt'),
        }

    # ── filter lists ──────────────────────────────────────────────────
    @api.model
    def get_response_dashboard_options(self):
        owners = self._read_group([('lead_owner', '!=', False)], ['lead_owner'], ['__count'])
        return {
            'sources': [{'id': s.id, 'name': s.name} for s in self.env['leads.sources'].sudo().search([])],
            'teams': [{'id': t.id, 'name': t.name} for t in self.env['lead.team'].sudo().search([])],
            'owners': sorted([{'id': o.id, 'name': o.sudo().name} for o, _c in owners], key=lambda x: x['name']),
        }

    # ── main payload ──────────────────────────────────────────────────
    @api.model
    def get_response_dashboard(self, date_from, date_to, source_id=False, team_id=False,
                               owner_id=False, group='day'):
        group = group if group in ('day', 'week', 'month', 'year') else 'day'
        flt = []
        if source_id:
            flt.append(('leads_source', '=', int(source_id)))
        if team_id:
            flt.append(('team_id', '=', int(team_id)))
        if owner_id:
            flt.append(('lead_owner', '=', int(owner_id)))
        dom = flt + [('create_date', '>=', self._rd_utc(date_from)),
                     ('create_date', '<', self._rd_utc(date_to, end=True))]

        return {
            'kpi': self._rd_stats(dom),
            'trend': self._rd_trend(dom, group),
            'averages': self._rd_averages(flt),
            'by_owner': self._rd_breakdown(dom, 'lead_owner'),
            'by_team': self._rd_breakdown(dom, 'team_id'),
            'by_source': self._rd_breakdown(dom, 'leads_source'),
            'fast_hours': CALLED_FAST_HRS,
        }

    def _rd_label(self, val, group):
        if not val:
            return '-'
        if group == 'month':
            return val.strftime('%b %Y')
        if group == 'year':
            return val.strftime('%Y')
        if group == 'week':
            return 'Wk ' + val.strftime('%d %b')
        return val.strftime('%d %b')

    def _rd_trend(self, dom, group):
        gb = 'create_date:%s' % group
        rows = {}
        for k, cnt in self._read_group(dom, [gb], ['__count']):
            rows[k] = {'k': k, 'leads': cnt, 'assign': 0.0, 'call': 0.0}
        for k, v in self._read_group(dom + [('first_assigned_dt', '!=', False)], [gb],
                                     ['assign_delay_hrs:avg']):
            if k in rows:
                rows[k]['assign'] = v or 0.0
        for k, v in self._read_group(dom + [('first_called_dt', '!=', False)], [gb],
                                     ['call_delay_hrs:avg']):
            if k in rows:
                rows[k]['call'] = v or 0.0
        out = []
        for k in sorted(rows, key=lambda x: str(x or '')):
            r = rows[k]
            out.append({'label': self._rd_label(k, group), 'leads': r['leads'],
                        'assign': round(r['assign'], 2), 'call': round(r['call'], 2)})
        return out

    def _rd_averages(self, flt):
        """Average delays for fixed windows (ignore the date picker, respect filters)."""
        today = fields.Date.context_today(self)
        wins = [
            ('Daily', 'Today', today, today),
            ('Weekly', 'Last 7 days', today - timedelta(days=6), today),
            ('Monthly', 'This month', today.replace(day=1), today),
            ('Yearly', 'This year', today.replace(month=1, day=1), today),
        ]
        out = []
        for title, sub, d1, d2 in wins:
            dom = flt + [('create_date', '>=', self._rd_utc(d1)), ('create_date', '<', self._rd_utc(d2, end=True))]
            s = self._rd_stats(dom)
            out.append({'title': title, 'sub': sub, 'leads': s['total'], 'avg_assign': s['avg_assign'],
                        'avg_call': s['avg_call'], 'fast_pct': s['fast_pct'], 'not_called': s['not_called']})
        return out

    def _rd_breakdown(self, dom, field):
        rows = {}

        def row(rec):
            key = rec.id if rec else 0
            return rows.setdefault(key, {
                'id': key, 'name': rec.sudo().display_name if rec else '(none)', 'leads': 0, 'assign': 0.0,
                'call': 0.0, 'called': 0, 'fast': 0})
        for rec, cnt in self._read_group(dom, [field], ['__count']):
            row(rec)['leads'] = cnt
        for rec, v in self._read_group(dom + [('first_assigned_dt', '!=', False)], [field],
                                       ['assign_delay_hrs:avg']):
            row(rec)['assign'] = v or 0.0
        for rec, v, cnt in self._read_group(dom + [('first_called_dt', '!=', False)], [field],
                                            ['call_delay_hrs:avg', '__count']):
            r = row(rec)
            r['call'] = v or 0.0
            r['called'] = cnt
        for rec, cnt in self._read_group(
                dom + [('first_called_dt', '!=', False), ('call_delay_hrs', '<=', CALLED_FAST_HRS)],
                [field], ['__count']):
            row(rec)['fast'] = cnt
        out = []
        for r in sorted(rows.values(), key=lambda x: -x['leads'])[:50]:
            r['assign'] = round(r['assign'], 2)
            r['call'] = round(r['call'], 2)
            r['not_called'] = r['leads'] - r['called']
            r['fast_pct'] = round(r['fast'] * 100.0 / r['leads'], 1) if r['leads'] else 0.0
            out.append(r)
        return out
