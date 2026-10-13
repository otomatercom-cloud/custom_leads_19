# -*- coding: utf-8 -*-
"""Officer bucket dashboard (Reports): per Admission Officer - leads in the bucket, leads received today with
their quality, and yesterday's received / re-assigned / lost. Lead counts honour the user's record rules."""
from datetime import timedelta

from odoo import api, fields, models

LOST_QUALITIES = ('not_interested', 'joined_other_institute', 'wrong_number', 'not_enquiry', 'crash_lead')


class LeadsLogicBucketDashboard(models.Model):
    _inherit = 'leads.logic'

    @api.model
    def _bd_employees(self):
        """Officers the current user may see (sudo lookup; the lead counts themselves use record rules)."""
        user, env = self.env.user, self.env
        Emp = env['hr.employee'].sudo()
        if user.has_group('custom_leads_19.group_super_admin') or user.has_group('custom_leads_19.group_lead_manager'):
            members = env['lead.team.member'].sudo().search([('team_id.active', '=', True)])
            return members.mapped('employee_id')
        if user.has_group('custom_leads_19.group_lead_team_lead'):
            teams = env['lead.team'].sudo().search([('active', '=', True), ('team_lead_ids.user_id', '=', user.id)])
            return teams.mapped('member_ids.employee_id') | Emp.search([('user_id', '=', user.id)])
        return Emp.search([('user_id', '=', user.id)])

    @api.model
    def get_bucket_dashboard(self, date=False):
        self = self.with_context(tz=self._rd_tzname())
        today = fields.Date.to_date(date) if date else fields.Date.context_today(self)
        yest = today - timedelta(days=1)
        t_s, t_e = self._rd_utc(today), self._rd_utc(today, end=True)
        y_s, y_e = self._rd_utc(yest), self._rd_utc(yest, end=True)
        emps = self._bd_employees().filtered(lambda e: e.active)
        ids = emps.ids
        labels = dict(self._fields['lead_quality'].selection)
        res = {'date': str(today), 'yesterday': str(yest), 'labels': labels, 'lost_qualities': list(LOST_QUALITIES),
               'ranges': {'t_s': fields.Datetime.to_string(t_s), 't_e': fields.Datetime.to_string(t_e),
                          'y_s': fields.Datetime.to_string(y_s), 'y_e': fields.Datetime.to_string(y_e)},
               'rows': []}
        if not ids:
            return res

        def count(dom):
            out = {}
            for o, n in self._read_group(dom + [('lead_owner', 'in', ids)], ['lead_owner'], ['__count']):
                out[o.id] = n
            return out

        bucket = count([])
        t_new = count([('assigned_date', '>=', t_s), ('assigned_date', '<', t_e)])
        y_new = count([('assigned_date', '>=', y_s), ('assigned_date', '<', y_e)])
        quality, bucket_q = {}, {}
        for o, q, n in self._read_group([('lead_owner', 'in', ids), ('assigned_date', '>=', t_s),
                                         ('assigned_date', '<', t_e)], ['lead_owner', 'lead_quality'], ['__count']):
            quality.setdefault(o.id, {})[q or 'none'] = n
        for o, q, n in self._read_group([('lead_owner', 'in', ids)], ['lead_owner', 'lead_quality'], ['__count']):
            bucket_q.setdefault(o.id, {})[q or 'none'] = n

        cr = self.env.cr
        # re-assigned away from / to an officer (previous owner taken from the assignment history)
        cr.execute("""
            WITH h AS (
                SELECT id, lead_id, owner_id, assigned_date,
                       LAG(owner_id) OVER (PARTITION BY lead_id ORDER BY assigned_date, id) AS prev
                  FROM lead_assignment_history
                 WHERE lead_id IN (SELECT lead_id FROM lead_assignment_history
                                    WHERE assigned_date >= %(s)s AND assigned_date < %(e)s))
            SELECT 'out', prev, count(DISTINCT lead_id) FROM h
             WHERE assigned_date >= %(s)s AND assigned_date < %(e)s AND prev IS NOT NULL
               AND owner_id IS DISTINCT FROM prev AND prev = ANY(%(ids)s) GROUP BY prev
            UNION ALL
            SELECT 'in', owner_id, count(DISTINCT lead_id) FROM h
             WHERE assigned_date >= %(s)s AND assigned_date < %(e)s AND prev IS NOT NULL
               AND owner_id IS DISTINCT FROM prev AND owner_id = ANY(%(ids)s) GROUP BY owner_id
        """, {'s': y_s, 'e': y_e, 'ids': ids})
        r_out, r_in = {}, {}
        for kind, emp, n in cr.fetchall():
            (r_out if kind == 'out' else r_in)[emp] = n
        # lost = leads the officer moved into a "lost" quality (distinct leads, by who changed it)
        uid_of = {e.id: e.user_id.id for e in emps}
        cr.execute("""
            SELECT user_id, (change_date >= %(ts)s) AS is_today, count(DISTINCT lead_id)
              FROM lead_quality_history
             WHERE change_date >= %(ys)s AND change_date < %(te)s AND lead_quality = ANY(%(q)s)
               AND user_id = ANY(%(u)s)
             GROUP BY user_id, (change_date >= %(ts)s)
        """, {'ys': y_s, 'ts': t_s, 'te': t_e, 'q': list(LOST_QUALITIES), 'u': [u for u in uid_of.values() if u]})
        lost_t, lost_y = {}, {}
        for uid, is_today, n in cr.fetchall():
            (lost_t if is_today else lost_y)[uid] = n

        for e in emps:
            u = uid_of.get(e.id)
            res['rows'].append({
                'id': e.id, 'name': e.name, 'bucket': bucket.get(e.id, 0), 'bucket_q': bucket_q.get(e.id, {}),
                'today': t_new.get(e.id, 0), 'today_q': quality.get(e.id, {}), 'today_lost': lost_t.get(u, 0),
                'y_new': y_new.get(e.id, 0), 'y_out': r_out.get(e.id, 0), 'y_in': r_in.get(e.id, 0),
                'y_lost': lost_y.get(u, 0)})
        res['rows'].sort(key=lambda r: (-r['today'], r['name'] or ''))
        return res
