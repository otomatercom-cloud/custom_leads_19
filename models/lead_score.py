# -*- coding: utf-8 -*-
"""Lead score (0-100) and the officer's "Call next" list.

Points per lead quality are an editable table (Lead Management Settings > Assignment > Call priority points);
freshness, calls so far, source, course and follow-up due have a weight each (Settings > Call priority).
Source and course points come from the real admission rate of the last 180 days."""
from datetime import timedelta

from odoo import api, fields, models, _

# Fallback only: the real points are the editable table "Call priority points" (lead.score.quality)
QUALITY_POINTS = {
    'hot': 60, 'waiting_for_admission': 56, 'warm': 50, 'follow_up': 46, 'new': 44, 'first_attempt': 42,
    'call_later': 38, 'cold': 28, 'may_be_later': 20, 'not_responding': 15, 'not_reachable': 10,
    'bad_lead': 8, 'crash_lead': 8,
}
WEIGHT_DEFAULTS = {'fresh': 15, 'calls': 10, 'source': 8, 'course': 4, 'due': 3}
FRESH_STEPS = ((1, 1.0), (4, 0.8), (24, 0.6), (72, 0.3), (168, 0.1))   # hours -> share of the freshness weight
CALL_SHARE = (1.0, 0.67, 0.4, 0.2, 0.07)                              # 0, 1, 2, 3, 4+ calls
CLOSED = ('admission', 'logic_students', 'joined_other_institute', 'wrong_number', 'not_enquiry', 'not_interested')
HISTORY_DAYS = 180
SCORE_WINDOW_DAYS = 120


class LeadScoreQuality(models.Model):
    _name = 'lead.score.quality'
    _description = 'Call priority points per lead quality'
    _order = 'points desc, id'

    quality = fields.Selection(selection=lambda self: self.env['lead.quality.config'].get_selection(),
                               string='Lead quality', required=True)
    points = fields.Integer(string='Priority points', required=True, default=0,
                            help='0-100. The bigger the number, the sooner officers are told to call this lead.')

    _quality_uniq = models.Constraint('UNIQUE(quality)', 'Each lead quality can be listed only once.')

    @api.model
    def action_recalc(self):
        self.env['leads.logic'].cron_update_call_scores()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Done'), 'message': _('Call priority scores were recalculated.'),
                           'type': 'success'}}


class LeadsLogicScore(models.Model):
    _inherit = 'leads.logic'

    call_score = fields.Integer(string='Call priority', index=True, copy=False, readonly=True,
                                help='0-100. Higher = call this lead sooner. Refreshed every 15 minutes.')

    @api.model
    def _score_config(self):
        """Quality points and the five weights, as set in the settings."""
        get = self.env['ir.config_parameter'].sudo().get_param
        cfg = {}
        for k, d in WEIGHT_DEFAULTS.items():
            try:
                cfg[k] = max(0, int(float(get('custom_leads_19.score_w_' + k) or d)))
            except (TypeError, ValueError):
                cfg[k] = d
        pts = {r.quality: r.points for r in self.env['lead.score.quality'].sudo().search([])}
        cfg['q'] = pts or dict(QUALITY_POINTS)
        return cfg

    @staticmethod
    def _score_fresh(hours, weight):
        for limit, share in FRESH_STEPS:
            if hours < limit:
                return weight * share
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
    def _score_leads(self, leads, src_rates, src_avg, crs_rates, crs_avg, calls, due, cfg):
        now = fields.Datetime.now()
        out = {}
        for r in leads:
            q = r['lead_quality']
            if q in CLOSED or r['state'] == 'lost':
                out[r['id']] = 0
                continue
            pts = cfg['q'].get(q or 'new', cfg['q'].get('new', 20))
            pts += self._score_fresh((now - r['create_date']).total_seconds() / 3600, cfg['fresh'])
            n = calls.get(r['id'], 0)
            pts += cfg['calls'] * CALL_SHARE[min(n, len(CALL_SHARE) - 1)]
            sid = r['leads_source'][0] if r['leads_source'] else 0
            pts += round(cfg['source'] * src_rates.get(sid, src_avg))
            crs = [crs_rates[c] for c in r['course_inter'] if c in crs_rates]
            pts += round(cfg['course'] * (max(crs) if crs else crs_avg))
            if r['id'] in due:
                pts += cfg['due']
            out[r['id']] = max(1, min(100, int(pts)))
        return out

    @api.model
    def cron_update_call_scores(self, batch=2000):
        """Scores every assigned, open lead of the last months in batches (SQL update, no write hooks)."""
        since = fields.Datetime.now() - timedelta(days=SCORE_WINDOW_DAYS)
        src_rates, src_avg = self._score_rates('leads_source')
        crs_rates, crs_avg = self._score_rates('course_inter')
        now = fields.Datetime.now()
        cfg = self._score_config()
        cr = self.env.cr
        cr.execute("SELECT DISTINCT lead_id FROM lead_followup WHERE status = 'scheduled' AND next_followup_date <= %s", (now,))
        due = {x[0] for x in cr.fetchall()}
        dom = ['|', ('lead_owner', '!=', False), ('topup_pool_lead', '=', True),
               '|', ('create_date', '>=', since), ('call_score', '>', 0)]
        ids = self.sudo().search(dom, order='id').ids
        done = 0
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            leads = self.sudo().browse(chunk).read(['lead_quality', 'state', 'create_date', 'leads_source', 'course_inter'])
            cr.execute("SELECT lead_id, COUNT(*) FROM lead_call_log WHERE lead_id = ANY(%s) GROUP BY lead_id", (chunk,))
            calls = dict(cr.fetchall())
            scores = self._score_leads(leads, src_rates, src_avg, crs_rates, crs_avg, calls, due, cfg)
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
