# -*- coding: utf-8 -*-
"""Odoo 17 cross-check: leads that exist in Odoo 19 AND in Odoo 17 (matched by phone number).

Anything Odoo 17 has and Odoo 19 does not - responses, call logs, follow-ups, quality history,
assignment history, empty lead fields, (optionally) chatter - is ADDED to the Odoo 19 lead.
Nothing is ever removed or overwritten in Odoo 19, and the lead owner is never changed."""
import logging
import re as _re
import time as _time
from datetime import datetime, time

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .odoo17_import import BATCH, SKIP_FIELDS, fix_escaped_html

_logger = logging.getLogger(__name__)

CHILD_SPECS = {
    'lead.response': ['user_id', 'comment', 'response_time'],
    'lead.call.log': ['user_id', 'call_time', 'remarks', 'call_uuid', 'caller_number',
                      'call_status', 'duration', 'recording_url', 'call_type'],
    'lead.followup': ['user_id', 'next_followup_date', 'remarks', 'phone_number', 'status'],
    'lead.quality.history': ['lead_quality', 'user_id', 'change_date'],
}
LABELS = {
    'lead.response': 'responses', 'lead.call.log': 'call logs', 'lead.followup': 'follow-ups',
    'lead.quality.history': 'quality history rows', 'assignment': 'assignment history rows',
    'chatter': 'chatter messages',
}
# never filled from Odoo 17 even when empty in Odoo 19
NO_FILL = SKIP_FIELDS | {
    'lead_quality', 'state', 'company_id', 'phone_number', 'name', 'leads_source', 'admission_status',
    'date_of_adding', 'last_update_date', 'odoo17_import_log_id', 'auto_reassign_count',
}


def _dt(v):
    return str(v)[:16] if v else ''


def _txt(v):
    return str(v or '').strip()


def _last10(v):
    return ''.join(c for c in str(v or '') if c.isdigit())[-10:]


def _sig(model, g):
    """Signature of one child row; `g(field)` returns its raw value (local record or converted vals)."""
    if model == 'lead.response':
        return (_txt(g('comment')), _dt(g('response_time')))
    if model == 'lead.call.log':
        uuid = _txt(g('call_uuid'))
        if uuid:
            return ('u', uuid)
        return ('t', _dt(g('call_time')), _last10(g('caller_number')), _txt(g('duration')))
    if model == 'lead.followup':
        return (_dt(g('next_followup_date')), _txt(g('remarks')))
    if model == 'lead.quality.history':
        return (_txt(g('lead_quality')), _dt(g('change_date')))
    return None


class LeadsLogicCrosscheck(models.Model):
    _inherit = 'leads.logic'

    odoo17_checked_on = fields.Datetime(string='Odoo 17 Cross-checked On', copy=False, readonly=True)


class OtmLeadsOdoo17Crosscheck(models.TransientModel):
    _name = 'otm.leads.odoo17.crosscheck.wizard'
    _description = 'Cross-check Odoo 19 Leads with Odoo 17'

    date_from = fields.Date(string='From Date', required=True,
                            default=lambda s: fields.Date.context_today(s))
    date_to = fields.Date(string='To Date', required=True,
                          default=lambda s: fields.Date.context_today(s))
    only_unlinked = fields.Boolean(
        string='Skip leads imported from Odoo 17', default=True,
        help='Leads that the Odoo 17 import already created have their history. Tick this off to '
             'check them too (they are matched by phone number as well).')
    recheck = fields.Boolean(
        string='Check again leads already cross-checked', default=False,
        help='Leads cross-checked before are skipped unless this is ticked.')
    copy_children = fields.Boolean(
        string='Add missing Responses, Call Logs, Follow-ups, Quality & Assignment History', default=True)
    copy_chatter = fields.Boolean(string='Add missing Chatter messages', default=False,
                                  help='Slower. Only messages that are not already in the lead are added.')
    fill_fields = fields.Boolean(
        string='Fill empty lead fields (course, place, email ...)', default=True,
        help='Only fields that are empty in Odoo 19 are filled. Nothing is overwritten.')
    copy_quality = fields.Boolean(
        string='Copy Lead Quality when Odoo 19 is still "New"', default=True,
        help='If the Odoo 19 lead is still New and Odoo 17 has a worked quality (Hot, Warm, RNR ...), '
             'the Odoo 17 quality is added. A quality already worked in Odoo 19 is never changed.')
    connection_info = fields.Char(readonly=True)
    result_text = fields.Text(string='Result', readonly=True)

    # ------------------------------------------------------------------ #
    def _local_domain(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("From Date must be before To Date."))
        tz = pytz.timezone(self.env.user.tz or 'Asia/Kolkata')

        def utc(d, t):
            return tz.localize(datetime.combine(d, t)).astimezone(pytz.utc).replace(tzinfo=None)

        dom = [('create_date', '>=', utc(self.date_from, time.min)),
               ('create_date', '<=', utc(self.date_to, time.max.replace(microsecond=0)))]
        if self.only_unlinked:
            dom += ['|', ('odoo17_lead_id', '=', 0), ('odoo17_lead_id', '=', False)]
        if not self.recheck:
            dom.append(('odoo17_checked_on', '=', False))
        return dom

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def action_preview(self):
        return self._run(dry=True)

    def action_run(self):
        return self._run(dry=False)

    # ------------------------------------------------------------------ #
    def _find_remote(self, call, leads):
        """{local lead id: [remote lead ids]} by the last 10 digits of the phone number."""
        phones = {l.id: _last10(l.phone_number) for l in leads}
        wanted = sorted({p for p in phones.values() if len(p) >= 8})
        if not wanted:
            return {}
        dom = [('phone_number', 'ilike', p) for p in wanted]
        dom = ['|'] * (len(dom) - 1) + dom
        rows = call('leads.logic', 'search_read', dom, fields=['phone_number'],
                    context={'active_test': False})
        by_phone = {}
        for r in rows:
            by_phone.setdefault(_last10(r.get('phone_number')), []).append(r['id'])
        return {lid: by_phone[p] for lid, p in phones.items() if p in by_phone}

    def _run(self, dry):
        self.ensure_one()
        helper = self.env['otm.leads.odoo17.import.wizard']
        call, info = helper._connect()
        Lead = self.env['leads.logic'].with_context(
            otm_odoo17_import=True, tracking_disable=True, mail_create_nolog=True, mail_notrigger=True,
            skip_pool_rules=True, urgent_lead_skip=True, skip_assignment_history=True)
        ids = Lead.sudo().search(self._local_domain(), order='id asc').ids
        rfields = call('leads.logic', 'fields_get', attributes=['type', 'relation', 'store'])
        local_fields = Lead._fields
        read_fields = sorted(
            f for f, d in rfields.items()
            if d.get('store') and (f in local_fields or f in ('lead_owner', 'write_date', 'create_date'))
            and d.get('type') not in ('one2many', 'binary', 'html'))
        ctx = {'cache': {}, 'sources_created': 0, 'campaigns_created': 0, 'warnings': []}
        stats = {'checked': 0, 'matched': 0, 'not_found': 0, 'fields_filled': 0, 'quality': 0}
        added = {k: 0 for k in LABELS}
        touched = []
        t0 = _time.time()
        budget = float(self.env['ir.config_parameter'].sudo().get_param('otm_odoo17.import_time_budget', 10)) * 4
        done_n = 0
        for start in range(0, len(ids), BATCH):
            if _time.time() - t0 > budget:
                break
            leads = Lead.sudo().browse(ids[start:start + BATCH])
            remote_map = self._find_remote(call, leads)
            all_remote = sorted({r for v in remote_map.values() for r in v})
            rows = {}
            if all_remote:
                for r in call('leads.logic', 'read', all_remote, fields=read_fields,
                              context={'active_test': False}):
                    rows[r['id']] = r
                if self.copy_children:
                    helper._prefetch_children(call, all_remote, ctx)
            for lead in leads:
                stats['checked'] += 1
                rids = remote_map.get(lead.id)
                try:
                    with self.env.cr.savepoint():
                        if not rids:
                            stats['not_found'] += 1
                        else:
                            stats['matched'] += 1
                            n = self._merge_lead(call, helper, lead, rids, rows, rfields, ctx, added, stats, dry)
                            if n:
                                touched.append(lead.reference_no)
                        if not dry:
                            lead.sudo().write({'odoo17_checked_on': fields.Datetime.now()})
                except Exception as e:  # noqa: BLE001
                    ctx['warnings'].append('%s: %s' % (lead.reference_no, str(e).strip()[:150]))
                    _logger.warning('Odoo17 cross-check failed for %s: %s', lead.id, e)
                done_n += 1
            if not dry:
                self.env.cr.commit()
                self.env.invalidate_all()
                _time.sleep(0.2)

        remaining = len(ids) - done_n
        lines = [
            ('PREVIEW - nothing was changed.' if dry else 'DONE - missing data was added.'),
            'Odoo 19 leads in range: %d   checked now: %d' % (len(ids), stats['checked']),
            'Found in Odoo 17: %d   not in Odoo 17: %d' % (stats['matched'], stats['not_found']),
            ('Would add' if dry else 'Added') + ': ' + (', '.join(
                '%d %s' % (n, LABELS[k]) for k, n in added.items() if n) or 'nothing missing'),
            '%s empty fields: %d   lead quality %s: %d' % (
                'Would fill' if dry else 'Filled', stats['fields_filled'],
                'would be copied' if dry else 'copied', stats['quality']),
        ]
        if remaining:
            lines.append('%d lead(s) not reached (time limit) - click again to continue%s.' % (
                remaining, '' if not dry else ' (preview covers the first leads only)'))
        if touched:
            lines.append('Leads updated (first 30): ' + ', '.join(touched[:30]))
        if ctx['warnings']:
            lines.append('--- Warnings (first 20) ---')
            lines.extend(sorted(set(ctx['warnings']))[:20])
        self.write({'result_text': '\n'.join(lines), 'connection_info': info})
        return self._reopen()

    # ------------------------------------------------------------------ #
    def _merge_lead(self, call, helper, lead, rids, rows, rfields, ctx, added, stats, dry):
        env = self.env
        lead = lead.sudo()
        changes = 0
        notes = []
        remote_rows = sorted((rows[r] for r in rids if r in rows), key=lambda r: r.get('write_date') or '',
                             reverse=True)          # newest Odoo 17 record first

        # ---- empty fields + quality ------------------------------------
        if self.fill_fields or self.copy_quality:
            fill, quality = {}, False
            for row in remote_rows:
                vals = helper._convert_vals(call, row, rfields, ctx)
                if self.copy_quality and not quality and vals.get('lead_quality') not in (None, False, 'new'):
                    quality = vals['lead_quality']
                if self.fill_fields:
                    for k, v in vals.items():
                        if k in NO_FILL or k in fill:
                            continue
                        lf = lead._fields[k]
                        if lf.type in ('boolean', 'integer', 'float', 'monetary'):
                            continue
                        if not lead[k]:
                            fill[k] = v
            if fill:
                stats['fields_filled'] += len(fill)
                changes += len(fill)
                notes.append('fields: ' + ', '.join(sorted(fill)))
            if quality and lead.lead_quality in (False, 'new'):
                stats['quality'] += 1
                changes += 1
                notes.append('quality: %s' % quality)
                fill['lead_quality'] = quality
            if fill and not dry:
                lead.write(fill)

        # ---- child rows -------------------------------------------------
        if self.copy_children:
            for model, flds in CHILD_SPECS.items():
                if model not in env:
                    continue
                Local = env[model].sudo().with_context(
                    otm_odoo17_import=True, tracking_disable=True, skip_pool_rules=True, urgent_lead_skip=True)
                avail = [f for f in flds if f in Local._fields]
                have = {_sig(model, lambda f, rec=rec: rec[f] if f in rec._fields else False)
                        for rec in Local.search([('lead_id', '=', lead.id)])}
                for rid in rids:
                    for r in (ctx.get('pf', {}).get(model) or {}).get(rid, []):
                        vals = {'lead_id': lead.id}
                        for f in avail:
                            lf = Local._fields[f]
                            v = r.get(f)
                            if lf.type == 'many2one':
                                v = helper._map_many2one(call, lf.comodel_name, (v or [0])[0], ctx) if v else False
                            elif lf.type == 'selection' and v:
                                if v not in {k for k, _l in lf._description_selection(env)}:
                                    continue
                            if v is False and lf.type != 'boolean':
                                continue
                            vals[f] = v
                        s = _sig(model, vals.get)
                        if s in have:
                            continue
                        have.add(s)
                        added[model] += 1
                        changes += 1
                        if not dry:
                            rec = Local.create(vals)
                            if r.get('create_date'):
                                env.cr.execute('UPDATE "%s" SET create_date=%%s WHERE id=%%s' % Local._table,
                                               (r['create_date'], rec.id))
            n = self._merge_assignment(call, helper, lead, rids, ctx, dry)
            added['assignment'] += n
            changes += n
            if changes and not dry:
                try:
                    lead.invalidate_recordset()
                    if hasattr(lead, '_compute_response_times'):
                        lead._compute_response_times()
                except Exception:  # noqa: BLE001
                    _logger.exception('response time recompute failed')

        # ---- chatter ----------------------------------------------------
        if self.copy_chatter:
            n = self._merge_chatter(call, helper, lead, rids, dry)
            added['chatter'] += n
            changes += n

        if changes and not dry:
            lead.with_context(mail_notrigger=True).message_post(
                body=_("Odoo 17 cross-check: %s.") % (', '.join(notes) or _('missing history added')))
        return changes

    def _merge_assignment(self, call, helper, lead, rids, ctx, dry):
        spec = helper._remote_assignment_model(call, ctx)
        if not spec:
            return 0
        pick, fg = spec['fields'], spec['types']
        Hist = self.env['lead.assignment.history'].sudo()
        have = {(h.owner_id.id, _dt(h.assigned_date)) for h in Hist.search([('lead_id', '=', lead.id)])}
        grouped = ctx.get('pf_ah') or {}
        n = 0
        for rid in rids:
            for r in grouped.get(rid, []):
                f = pick.get('owner')
                v = r.get(f) if f else False
                owner = helper._map_many2one(
                    call, fg[f].get('relation') or 'hr.employee',
                    v[0] if isinstance(v, (list, tuple)) else v, ctx) if v else False
                if not owner:
                    continue
                when = r.get(pick['date']) if 'date' in pick else False
                when = when or r.get('create_date') or fields.Datetime.now()
                key = (owner, _dt(when))
                if key in have:
                    continue
                have.add(key)
                n += 1
                if dry:
                    continue
                vals = {'lead_id': lead.id, 'owner_id': owner, 'assigned_date': when}
                bf = pick.get('by')
                bv = r.get(bf) if bf else False
                if bv:
                    by = helper._map_many2one(call, fg[bf].get('relation') or 'res.users',
                                              bv[0] if isinstance(bv, (list, tuple)) else bv, ctx)
                    if by:
                        vals['assigned_by'] = by
                Hist.create(vals)
        return n

    def _merge_chatter(self, call, helper, lead, rids, dry):
        Msg = self.env['mail.message'].sudo()

        def plain(b):
            return _re.sub(r'<[^>]+>', '', fix_escaped_html(b or '')).strip()[:80]

        have = {(_dt(m.date), plain(m.body)) for m in Msg.search(
            [('model', '=', 'leads.logic'), ('res_id', '=', lead.id)])}
        n = 0
        for rid in rids:
            rows = call('mail.message', 'search_read',
                        [('model', '=', 'leads.logic'), ('res_id', '=', rid),
                         ('message_type', 'in', ['comment', 'notification']), ('body', '!=', False)],
                        fields=['body', 'date', 'author_id', 'subject'], order='id asc')
            for r in rows:
                key = (_dt(r['date']), plain(r['body']))
                if not key[1] or key in have:
                    continue
                have.add(key)
                n += 1
                if dry:
                    continue
                author = False
                if r.get('author_id'):
                    author = self.env['res.partner'].sudo().search([('name', '=', r['author_id'][1])], limit=1).id
                Msg.create({
                    'model': 'leads.logic', 'res_id': lead.id, 'body': fix_escaped_html(r['body']),
                    'date': r['date'], 'author_id': author or False, 'message_type': 'comment',
                    'subtype_id': self.env.ref('mail.mt_note').id, 'subject': r.get('subject') or False})
        return n
