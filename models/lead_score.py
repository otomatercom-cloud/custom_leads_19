# -*- coding: utf-8 -*-
"""Lead score (0-100) and the officer's "Call next" list.

quality 35 + freshness 20 + calls so far 15 + source 12 + course 8 + follow-up due 10.
Source and course points come from the real admission rate of the last 180 days."""
from datetime import timedelta

from odoo import api, fields, models, _

QUALITY_POINTS = {
    'hot': 35, 'waiting_for_admission': 33, 'new': 30, 'first_attempt': 28, 'warm': 28, 'follow_up': 26,
    False: 25, 'call_later': 22, 'may_be_later': 12, 'cold': 10, 'not_responding': 8,
    'not_reachable': 6, 'bad_lead': 5, 'crash_lead': 5,
}
CLOSED = ('admission', 'logic_students', 'joined_other_institute', 'wrong_number', 'not_enquiry', 'not_interested')
CALL_POINTS = (15, 10, 6, 3)  # 0, 1, 2, 3 calls; 4+ = 1
HISTORY_DAYS = 180
SCORE_WINDOW_DAYS = 120


class LeadsLogicScore(models.Model):
    _inherit = 'leads.logic'

    call_score = fields.Integer(string='Call priority', index=True, copy=False, readonly=True,
                                help='0-100. Higher = call this lead sooner. Refreshed every 15 minutes.')

    @staticmethod
    def _score_fresh(hours):
        for limit, pts in ((1, 20), (4, 16), (24, 12), (72, 6), (168, 2)):
            if hours < limit:
                return pts
        return 0

    @api.model
    def _score_rates(self, field):
        """{id: admission rate} for sources / courses, scaled 0..1 against the best one (min 20 leads)."""
        since = fields.Datetime.now() - timedelta(days=HISTORY_DAYS)
        dom = [('create_date', '>=', since)]
        total = {r[0].id: r[1] for r in self._read_group(dom, [field], ['__count']) if r[0]}
        adm = {r[0].id: r[1] for r in self._read_group(dom + [('admission_status', '=', True)], [field], ['__count'])
               if r[0]}
        rates = {k: adm.get(k, 0) / n for k, n in total.items() if n >= 20}
        best = max(rates.values()) if rates else 0
        avg = (sum(rates.values()) / len(rates) / best) if rates and best else 0.5
        return {k: (v / best if best else 0) for k, v in rates.items()}, avg

    @api.model
    def _score_leads(self, leads, src_rates, src_avg, crs_rates, crs_avg, calls, due):
        now = fields.Datetime.now()
        out = {}
        for r in leads:
            q = r['lead_quality']
            if q in CLOSED or r['state'] == 'lost':
                out[r['id']] = 0
                continue
            pts = QUALITY_POINTS.get(q, 12)
            pts += self._score_fresh((now - r['create_date']).total_seconds() / 3600)
            n = calls.get(r['id'], 0)
            pts += CALL_POINTS[n] if n < len(CALL_POINTS) else 1
            sid = r['leads_source'][0] if r['leads_source'] else 0
            pts += round(12 * src_rates.get(sid, src_avg))
            crs = [crs_rates[c] for c in r['course_inter'] if c in crs_rates]
            pts += round(8 * (max(crs) if crs else crs_avg))
            if r['id'] in due:
                pts += 10
            out[r['id']] = max(1, min(100, int(pts)))
        return out

    @api.model
    def cron_update_call_scores(self, batch=2000):
        """Scores every assigned, open lead of the last months in batches (SQL update, no write hooks)."""
        since = fields.Datetime.now() - timedelta(days=SCORE_WINDOW_DAYS)
        src_rates, src_avg = self._score_rates('leads_source')
        crs_rates, crs_avg = self._score_rates('course_inter')
        now = fields.Datetime.now()
        cr = self.env.cr
        cr.execute("SELECT DISTINCT lead_id FROM lead_followup WHERE status = 'scheduled' AND next_followup_date <= %s", (now,))
        due = {x[0] for x in cr.fetchall()}
        dom = [('lead_owner', '!=', False), '|', ('create_date', '>=', since), ('call_score', '>', 0)]
        ids = self.sudo().search(dom, order='id').ids
        done = 0
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            leads = self.sudo().browse(chunk).read(['lead_quality', 'state', 'create_date', 'leads_source', 'course_inter'])
            cr.execute("SELECT lead_id, COUNT(*) FROM lead_call_log WHERE lead_id = ANY(%s) GROUP BY lead_id", (chunk,))
            calls = dict(cr.fetchall())
            scores = self._score_leads(leads, src_rates, src_avg, crs_rates, crs_avg, calls, due)
            cr.executemany('UPDATE leads_logic SET call_score = %s WHERE id = %s AND call_score IS DISTINCT FROM %s',
                           [(s, k, s) for k, s in scores.items()])
            done += len(chunk)
            cr.commit()
        self.env.invalidate_all()
        return done

    @api.model
    def action_open_call_next(self):
        """Officer's top leads, best first."""
        return {
            'type': 'ir.actions.act_window', 'name': _('Call next'), 'res_model': 'leads.logic',
            'view_mode': 'list,form', 'views': [(self.env.ref('custom_leads_19.view_leads_call_next_list').id, 'list'), (False, 'form')],
            'search_view_id': self.env.ref('custom_leads_19.view_leads_call_next_search').id,
            'domain': [('call_score', '>', 0)],
            'context': {'search_default_filter_mine': 1},
        }
