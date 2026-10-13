# -*- coding: utf-8 -*-
"""Conversion insight shown on the lead form: chance of joining (0-100) from call quality and customer approach,
the signals behind it, the call timeline, watch-outs and a suggested next step. Nothing is stored; it is worked out
when the form opens, from the call log, AI call analysis, responses, follow-ups and the lead quality."""
from datetime import timedelta

from odoo import api, fields, models

from .call_report import _is_connected, _parse_duration_seconds

# Weights of the chance of joining (sum 100)
W_QUALITY, W_CALLS, W_APPROACH, W_RECENT = 30, 25, 30, 15
INTEREST_PTS = {'hot': 95, 'warm': 75, 'unclear': 45, 'cold': 35, 'not_interested': 5}
CLOSED_NO = ('joined_other_institute', 'wrong_number', 'not_enquiry', 'not_interested', 'bad_lead', 'crash_lead')
TALK_FULL_SECS = 180          # an average of 3 minutes of talk per answered call = full marks


def _pct(v):
    return int(max(0, min(100, round(v))))


class LeadsLogicConversion(models.Model):
    _inherit = 'leads.logic'

    conv_insight = fields.Json(string='Conversion insight', compute='_compute_conv_insight')

    @api.depends('call_log_ids', 'call_log_ids.call_status', 'call_log_ids.duration', 'call_log_ids.ai_score',
                 'call_log_ids.ai_interest', 'lead_quality', 'followup_ids', 'followup_ids.status',
                 'response_ids', 'state')
    def _compute_conv_insight(self):
        for lead in self:
            try:
                lead.conv_insight = lead._conv_insight()
            except Exception:  # noqa: BLE001 - the form must always open
                lead.conv_insight = False

    def _conv_insight(self):
        self.ensure_one()
        lead = self.sudo()
        if not lead.id:
            return False
        now = fields.Datetime.now()
        q = lead.lead_quality or 'new'
        pts = {r.quality: r.points for r in self.env['lead.score.quality'].sudo().search([])}
        qpts = pts.get(q, 40)
        logs = lead.call_log_ids.filtered(lambda c: c.call_time).sorted('call_time')
        calls = []
        for c in logs:
            secs = _parse_duration_seconds(c.duration)
            calls.append({'time': c.call_time, 'secs': secs, 'ok': bool(_is_connected(c.call_status, secs)),
                          'type': c.call_type, 'ai_score': c.ai_score, 'interest': c.ai_interest,
                          'issues': (c.ai_issues or '').strip(), 'next': (c.ai_next_step or '').strip()})
        total, answered = len(calls), [c for c in calls if c['ok']]

        # call quality
        talk = _pct(100.0 * (sum(c['secs'] for c in answered) / len(answered)) / TALK_FULL_SECS) if answered else 0
        rate = _pct(100.0 * len(answered) / total) if total else 0
        ai_scores = [c['ai_score'] for c in calls if c['ai_score']]
        pitch = _pct(10.0 * sum(ai_scores) / len(ai_scores)) if ai_scores else None
        cq_parts = [talk, rate] + ([pitch] if pitch is not None else [])
        call_quality = _pct(sum(cq_parts) / len(cq_parts)) if total else 0

        # customer approach
        interests = [c['interest'] for c in calls if c['interest']]
        interest = INTEREST_PTS.get(interests[-1]) if interests else None
        if interest is None:
            interest = _pct(100.0 * min(1.0, qpts / 60.0))
        engage = _pct(100.0 * min(3, len(lead.response_ids)) / 3)
        sched = lead.followup_ids.filtered(lambda f: f.status == 'scheduled')
        agreed = 90 if sched else 30
        issues = [c['issues'] for c in calls if c['issues']]
        objections = _pct(100 - 25 * len(issues))
        approach = _pct((interest * 2 + engage + agreed + objections) / 5.0)

        # recency of a real conversation
        last_ok = answered[-1]['time'] if answered else None
        age_h = (now - last_ok).total_seconds() / 3600.0 if last_ok else None
        recent = 0 if age_h is None else 100 if age_h <= 72 else 60 if age_h <= 168 else 20
        qn = _pct(100.0 * min(1.0, qpts / 60.0))

        chance = _pct((W_QUALITY * qn + W_CALLS * call_quality + W_APPROACH * approach + W_RECENT * recent) / 100.0)
        if lead.state == 'lost' or q in CLOSED_NO:
            chance = min(chance, 5)
        if q in ('admission', 'logic_students') or lead.admission_status:
            chance = 100
        band = 'high' if chance >= 70 else 'medium' if chance >= 40 else 'low'

        # watch-outs
        watch = []
        if issues:
            watch.append({'level': 'bad', 'text': issues[-1][:90]})
        if total and not answered:
            watch.append({'level': 'warn', 'text': '%s call(s), none answered yet' % total})
        last_call = calls[-1]['time'] if calls else None
        if last_call and (now - last_call) > timedelta(hours=24) and lead.state != 'lost':
            watch.append({'level': 'warn', 'text': 'No call for %s hours' % int((now - last_call).total_seconds() / 3600)})
        overdue = sched.filtered(lambda f: f.next_followup_date and f.next_followup_date < now)
        if overdue:
            watch.append({'level': 'bad', 'text': 'A follow-up is overdue'})
        if not total:
            watch.append({'level': 'warn', 'text': 'Not called yet'})

        # next step
        steps = []
        ai_next = next((c['next'] for c in reversed(calls) if c['next']), '')
        if ai_next:
            steps.append(ai_next[:90])
        if not total:
            steps.append('Call this lead now')
        elif sched:
            nxt = min(sched.mapped('next_followup_date') or [False])
            if nxt:
                steps.append('Follow up on %s' % fields.Datetime.context_timestamp(self, nxt).strftime('%d %b, %I:%M %p'))
        if total and not answered:
            steps.append('Try a different time of day')
        if not steps:
            steps.append('Share the fee plan and ask for a joining date')

        def lbl(dt):
            return fields.Datetime.context_timestamp(self, dt).strftime('%d %b')
        return {
            'chance': chance, 'band': band,
            'call_quality': call_quality, 'approach': approach,
            'quality_rows': [
                {'label': 'Talk time', 'value': talk, 'note': ('%s m %s s' % divmod(int(sum(c['secs'] for c in answered) / len(answered)), 60)) if answered else 'No talk yet'},
                {'label': 'Calls answered', 'value': rate, 'note': '%s of %s' % (len(answered), total)},
                {'label': 'Pitch clarity', 'value': pitch if pitch is not None else 0,
                 'note': ('%s / 10' % round(sum(ai_scores) / len(ai_scores), 1)) if ai_scores else 'Not analysed'},
            ],
            'approach_rows': [
                {'label': 'Interest', 'value': interest, 'note': (interests[-1] or '').replace('_', ' ').title() if interests else q.replace('_', ' ').title()},
                {'label': 'Engagement', 'value': engage, 'note': '%s response(s)' % len(lead.response_ids)},
                {'label': 'Follow-up set', 'value': agreed, 'note': 'Yes' if sched else 'No'},
                {'label': 'Objections', 'value': objections, 'note': '%s raised' % len(issues) if issues else 'None'},
            ],
            'timeline': [{'label': lbl(c['time']), 'secs': c['secs'], 'ok': c['ok']} for c in calls[-8:]],
            'watch': watch[:3], 'steps': steps[:3],
        }
