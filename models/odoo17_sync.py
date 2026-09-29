import json
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

# Odoo 19 -> Odoo 17 one-way sync: only these lead fields are pushed.
SYNC_FIELDS = [
    'name', 'phone_number', 'phone_number_second', 'email_address', 'parent_number',
    'lead_quality', 'state', 'current_status', 'lost_reason', 'remarks',
    'next_follow_up_date', 'expected_joining_date', 'closing_date',
    'lead_owner', 'tele_caller_id', 'leads_source', 'source_campaign_id',
    'place', 'district', 'college_name', 'academic_year',
]
MAX_ATTEMPTS = 5
PER_RUN = 100


class OtmLeadsOdoo17SyncQueue(models.Model):
    _name = 'otm.leads.odoo17.sync.queue'
    _description = 'Odoo 17 Lead Sync Queue'
    _order = 'id desc'

    lead_id = fields.Many2one('leads.logic', string='Lead', index=True, ondelete='cascade')
    odoo17_lead_id = fields.Integer(string='Odoo 17 Lead ID', index=True)
    payload = fields.Text(string='Changes (JSON)')
    state = fields.Selection(
        [('pending', 'Pending'), ('done', 'Done'), ('failed', 'Failed')],
        default='pending', index=True)
    attempts = fields.Integer(default=0)
    error = fields.Text()
    done_date = fields.Datetime()

    # ------------------------------------------------------------------ #
    @api.model
    def _sync_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param('otm_odoo17.sync_enabled') == 'True' or \
            self.env['ir.config_parameter'].sudo().get_param('otm_odoo17.sync_enabled') == '1'

    @api.model
    def _enqueue(self, lead, fnames):
        """Store a descriptor of the CURRENT values of fnames for the lead."""
        payload = {}
        for f in fnames:
            fld = lead._fields[f]
            v = lead[f]
            if fld.type == 'many2one':
                if not v:
                    payload[f] = {'t': 'm2o', 'rel': fld.comodel_name, 'key': False}
                else:
                    key = v.login if fld.comodel_name == 'res.users' else v.display_name
                    payload[f] = {'t': 'm2o', 'rel': fld.comodel_name, 'key': key,
                                  'parent': (v.lead_source_id.name if fld.comodel_name == 'lead.source.campaign'
                                             and v.lead_source_id else False)}
            elif fld.type in ('date', 'datetime'):
                payload[f] = {'t': 'v', 'v': fields.Date.to_string(v) if fld.type == 'date'
                              else fields.Datetime.to_string(v) if v else False}
            else:
                payload[f] = {'t': 'v', 'v': v if v not in (None,) else False}
        rec = self.sudo().search([('lead_id', '=', lead.id), ('state', '=', 'pending')], limit=1)
        if rec:  # coalesce with the pending item
            old = json.loads(rec.payload or '{}')
            old.update(payload)
            rec.payload = json.dumps(old)
        else:
            self.sudo().create({'lead_id': lead.id, 'odoo17_lead_id': lead.odoo17_lead_id,
                                'payload': json.dumps(payload)})

    # ------------------------------------------------------------------ #
    def _remote_id(self, call, rel, key, parent, cache):
        if not key:
            return False
        ck = (rel, key, parent)
        if ck in cache:
            return cache[ck]
        ctx = {'active_test': False}
        if rel == 'res.users':
            dom = [('login', '=', key)]
        elif rel == 'lead.source.campaign':
            dom = [('name', '=ilike', key)]
        else:
            dom = [('name', '=ilike', key)]
        ids = call(rel, 'search', dom, limit=5, context=ctx)
        if rel == 'lead.source.campaign' and parent and len(ids) > 1:
            for r in call(rel, 'read', ids, fields=['lead_source_id']):
                if r['lead_source_id'] and r['lead_source_id'][1].lower() == parent.lower():
                    ids = [r['id']]
                    break
        res = ids[0] if ids else False
        cache[ck] = res
        return res

    def _push(self, call, rfields, cache):
        self.ensure_one()
        payload = json.loads(self.payload or '{}')
        vals = {}
        notes = []
        for f, d in payload.items():
            rf = rfields.get(f)
            if not rf:
                continue
            if d['t'] == 'm2o':
                if rf.get('type') != 'many2one':
                    continue
                rid = self._remote_id(call, d['rel'], d['key'], d.get('parent'), cache)
                if d['key'] and not rid:
                    notes.append('%s "%s" not found in Odoo 17 - skipped' % (f, d['key']))
                    continue
                vals[f] = rid
            else:
                v = d['v']
                if rf.get('type') == 'selection' and v:
                    keys = {k for k, _l in rf.get('selection') or []}
                    if keys and v not in keys:
                        notes.append('%s value "%s" not valid in Odoo 17 - skipped' % (f, v))
                        continue
                vals[f] = v
        if vals:
            call('leads.logic', 'write', [self.odoo17_lead_id], vals,
                 context={'tracking_disable': True, 'otm_odoo19_sync': True})
        return notes

    @api.model
    def cron_process_queue(self):
        if not self._sync_enabled():
            return
        items = self.sudo().search(
            [('state', '=', 'pending'), ('attempts', '<', MAX_ATTEMPTS)], order='id', limit=PER_RUN)
        if not items:
            return
        try:
            call, _info = self.env['otm.leads.odoo17.import.wizard']._connect()
            rfields = call('leads.logic', 'fields_get', attributes=['type', 'selection'])
        except Exception as e:
            _logger.warning('Odoo17 sync: connection failed: %s', e)
            items.write({'attempts': 0})  # server down is not the lead's fault - keep pending
            return
        cache = {}
        for it in items:
            try:
                with self.env.cr.savepoint():
                    notes = it._push(call, rfields, cache)
                    it.write({'state': 'done', 'done_date': fields.Datetime.now(),
                              'error': '\n'.join(notes) or False})
            except Exception as e:
                att = it.attempts + 1
                it.write({'attempts': att, 'error': str(e)[:1500],
                          'state': 'failed' if att >= MAX_ATTEMPTS else 'pending'})
            self.env.cr.commit()

    def action_retry(self):
        self.filtered(lambda r: r.state == 'failed').write({'state': 'pending', 'attempts': 0})

    @api.model
    def action_process_now(self):
        self.cron_process_queue()
        return True


class LeadsLogicOdoo17Sync(models.Model):
    _inherit = 'leads.logic'

    def write(self, vals):
        res = super().write(vals)
        ctx = self.env.context
        if ctx.get('otm_odoo17_import') or ctx.get('otm_odoo17_sync_skip'):
            return res
        fnames = [f for f in SYNC_FIELDS if f in vals and f in self._fields]
        if fnames:
            Queue = self.env['otm.leads.odoo17.sync.queue']
            if Queue._sync_enabled():
                for lead in self.filtered('odoo17_lead_id'):
                    Queue._enqueue(lead, fnames)
        return res
