import html as _html
import logging
import re as _re
import time as _time
import xmlrpc.client
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BATCH = 25

# Never copied from Odoo 17 (handled explicitly, technical or unsafe)
SKIP_FIELDS = {
    'id', 'reference_no', 'odoo17_lead_id', 'message_ids', 'message_follower_ids',
    'activity_ids', 'website_message_ids', 'create_uid', 'write_uid', 'create_date',
    'write_date', 'display_name', 'lead_owner', 'tele_caller_id', 'lead_creator_id',
    'student_id', 'adm_id', 'sample', 'progress_html', 'masked_phone', 'show_phone',
}

# One2many children imported in a dedicated step: (remote model, local model, link field)
CHILD_MODELS = ('lead.response', 'lead.call.log', 'lead.followup', 'lead.quality.history')


_ESCAPED_TAG = _re.compile(r'&lt;/?(b|br|strong|i|em|u|p|div|span|ul|ol|li|a)\b', _re.I)


def fix_escaped_html(body):
    """Odoo 17 code that posted HTML as a plain string stored it escaped ('&lt;b&gt;New...'),
    so chatter shows raw tags. Turn it back into real markup (one unescape pass only)."""
    if body and _ESCAPED_TAG.search(body):
        return _html.unescape(body)
    return body



class OtmLeadsOdoo17ImportLog(models.Model):
    _name = 'otm.leads.odoo17.import.log'
    _description = 'Odoo 17 Leads Import Log'
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, default=lambda s: _('New'))
    date_from = fields.Date(string='From', readonly=True)
    date_to = fields.Date(string='To', readonly=True)
    date_field = fields.Char(string='Filtered On', readonly=True)
    user_id = fields.Many2one('res.users', string='Run By', default=lambda s: s.env.user, readonly=True)
    fetched_count = fields.Integer(string='Fetched', readonly=True)
    created_count = fields.Integer(string='Created', readonly=True)
    duplicate_count = fields.Integer(string='Skipped (Phone Duplicate)', readonly=True)
    already_count = fields.Integer(string='Already Imported Earlier', readonly=True)
    remaining_count = fields.Integer(string='Remaining (click Import again)', readonly=True)
    failed_count = fields.Integer(string='Failed', readonly=True)
    campaigns_created = fields.Integer(string='Campaigns Created', readonly=True)
    sources_created = fields.Integer(string='Sources Created', readonly=True)
    details = fields.Text(string='Details', readonly=True)
    state = fields.Selection([('done', 'Done'), ('running', 'Continuing in background'),
                              ('failed', 'Stopped (error)')],
                             default='done', readonly=True)
    last_activity = fields.Datetime(string='Last Activity', readonly=True)
    stalled = fields.Boolean(string='Stalled', compute='_compute_stalled')
    stop_hint = fields.Char(string='Why it may have stopped', compute='_compute_stalled')

    def _compute_stalled(self):
        cron = self.env.ref('custom_leads_19.cron_otm_leads_odoo17_import', raise_if_not_found=False)
        limit = fields.Datetime.now() - timedelta(minutes=5)
        for rec in self:
            idle = rec.state == 'running' and (not rec.last_activity or rec.last_activity < limit)
            rec.stalled = idle or rec.state == 'failed'
            hint = ''
            if idle:
                hint = _('No lead was imported for over 5 minutes. ')
                if cron and not cron.sudo().active:
                    hint += _('The background job "Continue Odoo 17 import" is switched off (Odoo switches a job off '
                              'after repeated failures or time-outs). Click Resume import.')
                else:
                    hint += _('The background job was probably stopped by the server time limit or a restart. '
                              'Click Resume import.')
            elif rec.state == 'failed':
                hint = _('The import stopped with an error - see Details. Fix it and click Resume import.')
            rec.stop_hint = hint

    def action_mark_done(self):
        """Stop a running/failed import log (for example an old duplicate) so a new import can start."""
        self.write({'state': 'done'})
        return True

    def action_resume(self):
        """Switch the background job back on and continue this import now."""
        self.ensure_one()
        cron = self.env.ref('custom_leads_19.cron_otm_leads_odoo17_import', raise_if_not_found=False)
        if cron:
            cron.sudo().write({'active': True})
        self.write({'state': 'running', 'last_activity': fields.Datetime.now()})
        if cron:
            cron.sudo()._trigger()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Import'), 'message': _('Import resumed in the background. Refresh in a minute.'),
                           'type': 'success'}}
    params = fields.Text(readonly=True)
    lead_ids = fields.One2many('leads.logic', 'odoo17_import_log_id', string='Imported Leads')

    def _continue_one(self, budget):
        """Run one time-boxed slice of this import log (used by the cron and the manual button)."""
        import json
        self.ensure_one()
        log = self
        try:
            p = json.loads(log.params or '{}')
            wiz = self.env['otm.leads.odoo17.import.wizard'].with_user(log.user_id or self.env.user).create({
                'date_from': p['date_from'], 'date_to': p['date_to'], 'date_field': p['date_field'],
                'import_children': p['import_children'], 'import_chatter': p['import_chatter'],
                'import_reenquiries': p['import_reenquiries'],
            })
            ids = p.get('campaign_remote_ids') or []
            if ids:
                opts = self.env['otm.leads.odoo17.campaign.option'].create(
                    [{'remote_id': i, 'name': str(i)} for i in ids])
                wiz.campaign_option_ids = [(6, 0, opts.ids)]
            wiz._run_import(log=log, budget=budget)
            self.env.cr.commit()
            return True
        except Exception as e:
            self.env.cr.rollback()
            _logger.exception('Odoo17 background import failed')
            log.write({'state': 'failed', 'details': (log.details or '') + '\nImport stopped: %s' % e})
            self.env.cr.commit()
            return False

    @api.model
    def cron_continue_imports(self):
        """Continue interrupted imports in the background (no HTTP timeout here)."""
        budget = float(self.env['ir.config_parameter'].sudo().get_param('otm_odoo17.bg_time_budget', 30))
        for log in self.search([('state', '=', 'running')], order='id', limit=1):
            log._continue_one(budget)

    def action_run_batch(self):
        """Manual driver: process one slice now (about 15 s) - works even if the background job is not running."""
        self.ensure_one()
        if self.state == 'done':
            return True
        if self.state == 'failed':
            self.write({'state': 'running'})
        if not self.params:
            raise UserError(_("This log has no saved settings to continue from. Start a new import instead."))
        ok = self._continue_one(15)
        return {'type': 'ir.actions.client', 'tag': 'reload'} if ok else {
            'type': 'ir.actions.client', 'tag': 'reload'}


class OtmLeadsOdoo17CampaignOption(models.TransientModel):
    """Odoo 17 Source Campaign shown in the import wizard's multi-select."""
    _name = 'otm.leads.odoo17.campaign.option'
    _description = 'Odoo 17 Source Campaign (import option)'

    remote_id = fields.Integer(index=True)
    name = fields.Char(required=True)
    source_name = fields.Char()

    @api.depends('name', 'source_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s / %s' % (rec.source_name, rec.name) if rec.source_name else rec.name


class OtmLeadsOdoo17ImportWizard(models.TransientModel):
    _name = 'otm.leads.odoo17.import.wizard'
    _description = 'Import Leads from Odoo 17'

    date_from = fields.Date(string='From Date', required=True,
                            default=lambda s: fields.Date.context_today(s))
    date_to = fields.Date(string='To Date', required=True,
                          default=lambda s: fields.Date.context_today(s))
    date_field = fields.Selection(
        [('create_date', 'Created On (system)'), ('date_of_adding', 'Date of Adding')],
        string='Filter By', default='create_date', required=True)
    import_children = fields.Boolean(
        string='Import Responses, Call Logs, Follow-ups & Quality & Assignment History', default=True)
    import_chatter = fields.Boolean(
        string='Import Chatter Messages', default=False,
        help='Copies comments/notes from the Odoo 17 chatter. Slower.')
    import_reenquiries = fields.Boolean(
        string='Also Import Re-Attempts (Re-Enquiries)', default=True,
        help='Also brings the Odoo 17 Re-Enquiry records whose Enquiry Date is in the same date range '
             '(and whose lead is in the selected Source Campaigns) as Odoo 19 Re-Attempt records. '
             'Their leads are imported too, even if the lead itself is older than the range.')
    preview_details = fields.Text(string='Count Details', readonly=True)
    campaign_option_ids = fields.Many2many(
        'otm.leads.odoo17.campaign.option', 'otm_l17_wiz_camp_opt_rel', 'wizard_id', 'option_id',
        string='Source Campaigns',
        help='Only import leads of these Odoo 17 Source Campaigns. Leave empty for all.')
    campaigns_loaded = fields.Boolean()
    preview_count = fields.Integer(string='Leads Found in Odoo 17', readonly=True)
    connection_info = fields.Char(string='Connection', readonly=True)

    # ------------------------------------------------------------------ #
    # Connection - reuses the connection already configured for the      #
    # Placement module. Everything that depends on how that connection   #
    # is stored is isolated in _get_odoo17_connection().                 #
    # ------------------------------------------------------------------ #
    @api.model
    def _get_odoo17_connection(self):
        """Return dict(url, db, login, password) of the Odoo 17 server.

        Order:
          1. ir.config_parameter  otm_odoo17.url / .db / .login / .password
          2. Auto-detect a record of any installed model whose name contains
             'placement' (or 'odoo17') that has url/db/user/password-like fields.
        """
        icp = self.env['ir.config_parameter'].sudo()
        cfg = {k: icp.get_param('otm_odoo17.%s' % k) for k in ('url', 'db', 'login', 'password')}
        if all(cfg.values()):
            return cfg

        Model = self.env['ir.model'].sudo()
        candidates = Model.search(['|', ('model', 'ilike', 'placement'), ('model', 'ilike', 'odoo17')])
        aliases = {
            'url': ('url', 'server_url', 'odoo_url', 'host', 'base_url', 'odoo17_url'),
            'db': ('db', 'database', 'db_name', 'odoo_db', 'dbname', 'odoo17_db'),
            'login': ('login', 'username', 'user', 'user_name', 'odoo_user', 'odoo_username', 'odoo17_user'),
            'password': ('password', 'api_key', 'apikey', 'odoo_password', 'secret', 'odoo17_password'),
        }
        for im in candidates:
            if im.model not in self.env or self.env[im.model]._transient:
                continue
            fields_ = self.env[im.model]._fields
            picked = {}
            for key, names in aliases.items():
                for n in names:
                    if n in fields_:
                        picked[key] = n
                        break
            if len(picked) < 4:
                continue
            rec = self.env[im.model].sudo().search([], order='id desc', limit=1)
            if rec and all(rec[picked[k]] for k in picked):
                return {k: rec[picked[k]] for k in picked}
        # Settings fields on res.config.settings are stored as ir.config_parameter -> try them too
        raise UserError(_(
            "Odoo 17 connection not found. Set the system parameters otm_odoo17.url, "
            "otm_odoo17.db, otm_odoo17.login and otm_odoo17.password (Settings > Technical > "
            "System Parameters), or map your Placement module's connection in "
            "_get_odoo17_connection()."))

    def _connect(self):
        cfg = self._get_odoo17_connection()
        url = (cfg['url'] or '').rstrip('/')
        if not url.startswith('http'):
            url = 'https://' + url
        try:
            common = xmlrpc.client.ServerProxy('%s/xmlrpc/2/common' % url, allow_none=True)
            uid = common.authenticate(cfg['db'], cfg['login'], cfg['password'], {})
        except Exception as e:
            raise UserError(_("Cannot reach Odoo 17 server: %s") % e)
        if not uid:
            raise UserError(_("Odoo 17 authentication failed (check database / login / password)."))
        models_proxy = xmlrpc.client.ServerProxy('%s/xmlrpc/2/object' % url, allow_none=True)
        db, pwd = cfg['db'], cfg['password']

        def call(model, method, *args, **kw):
            return models_proxy.execute_kw(db, uid, pwd, model, method, list(args), kw)

        return call, '%s (%s)' % (url, cfg['db'])

    # ------------------------------------------------------------------ #
    def _remote_domain(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("From Date must be before To Date."))
        if self.date_field == 'date_of_adding':
            return [('date_of_adding', '>=', str(self.date_from)),
                    ('date_of_adding', '<=', str(self.date_to))] + campaign_dom
        tz = pytz.timezone(self.env.user.tz or 'Asia/Kolkata')
        campaign_dom = []
        if self.campaign_option_ids:
            campaign_dom = [('source_campaign_id', 'in', self.campaign_option_ids.mapped('remote_id'))]

        def to_utc(d, t):
            return tz.localize(datetime.combine(d, t)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        return [('create_date', '>=', to_utc(self.date_from, time.min)),
                ('create_date', '<=', to_utc(self.date_to, time.max.replace(microsecond=0)))] + campaign_dom

    def action_load_campaigns(self):
        """Fetch the Odoo 17 Source Campaigns so they can be picked (multi-select)."""
        self.ensure_one()
        call, info = self._connect()
        rows = call('lead.source.campaign', 'search_read', [], fields=['name', 'lead_source_id'],
                    order='name asc', context={'active_test': False})
        Opt = self.env['otm.leads.odoo17.campaign.option']
        self.campaign_option_ids = [(5, 0, 0)]
        Opt.search([]).unlink()          # transient: only this user's old lists
        Opt.create([{'remote_id': r['id'], 'name': r['name'],
                     'source_name': (r['lead_source_id'] or [0, ''])[1] or False} for r in rows])
        self.write({'campaigns_loaded': True, 'connection_info': info})
        return self._reopen()

    def _reenquiry_domain(self):
        self.ensure_one()
        dom = [('enquiry_date', '>=', str(self.date_from)), ('enquiry_date', '<=', str(self.date_to))]
        if self.campaign_option_ids:
            dom.append(('lead_id.source_campaign_id', 'in', self.campaign_option_ids.mapped('remote_id')))
        return dom

    def _analyse(self, call):
        """Work out, without importing anything, what an import would do.

        Returns dict: all_ids, re_rows, already_ids, dup_ids, new_ids, campaign_counts, extra_re
        Only ids + phone numbers are read from Odoo 17, so this is fast.
        """
        self.ensure_one()
        domain = self._remote_domain()
        main_ids = call('leads.logic', 'search', domain, order='id asc')
        groups = call('leads.logic', 'read_group', domain, ['source_campaign_id'],
                      ['source_campaign_id'], lazy=False)
        campaign_counts = sorted(
            [((g['source_campaign_id'] or [0, '(no campaign)'])[1], g['__count']) for g in groups],
            key=lambda x: -x[1])
        re_rows, extra_re = [], 0
        all_ids = list(main_ids)
        if self.import_reenquiries:
            re_rows = call('lead.re.enquiry', 'search_read', self._reenquiry_domain(),
                           fields=['lead_id'], order='id asc')
            extra = sorted({r['lead_id'][0] for r in re_rows if r['lead_id']} - set(main_ids))
            extra_re = len(extra)
            all_ids += extra
        # phones
        phones = {}
        for i in range(0, len(all_ids), 500):
            for r in call('leads.logic', 'read', all_ids[i:i + 500], fields=['phone_number']):
                phones[r['id']] = ''.join((r.get('phone_number') or '').split())[-10:]
        Lead = self.env['leads.logic'].sudo()
        already = set(Lead.search([('odoo17_lead_id', 'in', all_ids)]).mapped('odoo17_lead_id')) if all_ids else set()
        self.env.cr.execute(
            "SELECT DISTINCT RIGHT(REPLACE(phone_number, ' ', ''), 10) FROM leads_logic "
            "WHERE phone_number IS NOT NULL")
        local_phones = {r[0] for r in self.env.cr.fetchall()}
        seen, dup_ids, new_ids = set(), [], []
        for i in all_ids:
            if i in already:
                continue
            ph = phones.get(i)
            if ph and (ph in local_phones or ph in seen):
                dup_ids.append(i)
            else:
                new_ids.append(i)
                if ph:
                    seen.add(ph)
        return {'all_ids': all_ids, 'main_count': len(main_ids), 're_rows': re_rows, 'extra_re': extra_re,
                'already_ids': sorted(already), 'dup_ids': dup_ids, 'new_ids': new_ids,
                'campaign_counts': campaign_counts}

    def _preview_text(self, an):
        lines = ['Leads in date range%s: %d' % (
            ' (selected campaigns)' if self.campaign_option_ids else '', an['main_count'])]
        for name, cnt in an['campaign_counts']:
            lines.append('   - %s: %d' % (name, cnt))
        if self.import_reenquiries:
            lines.append('Re-Attempts (Re-Enquiries) in date range: %d  (+%d extra older leads)' % (
                len(an['re_rows']), an['extra_re']))
        lines += [
            '',
            'SELECTED FOR IMPORT (total leads fetched): %d' % len(an['all_ids']),
            '   - already imported earlier: %d' % len(an['already_ids']),
            '   - skipped, phone number already exists in Odoo 19 (or repeated in this list): %d' % len(an['dup_ids']),
            '   - NEW leads that will be imported: %d' % len(an['new_ids']),
        ]
        return '\n'.join(lines)

    def _refresh_preview(self):
        """Fill preview fields (used by the button and by onchange)."""
        self.ensure_one()
        call, info = self._connect()
        an = self._analyse(call)
        self.preview_count = an['main_count']
        self.connection_info = info
        self.preview_details = self._preview_text(an)
        return an

    def action_test_connection(self):
        self.ensure_one()
        self._refresh_preview()
        return self._reopen()

    @api.onchange('campaign_option_ids', 'date_from', 'date_to', 'date_field', 'import_reenquiries')
    def _onchange_refresh_preview(self):
        for rec in self:
            if not (rec.date_from and rec.date_to):
                continue
            try:
                rec._refresh_preview()
            except Exception as e:  # never block the form because the count failed
                rec.preview_details = _('Count not available: %s') % str(e)[:200]

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    # ------------------------------------------------------------------ #
    # Mapping helpers (all cached per run)                               #
    # ------------------------------------------------------------------ #
    def _map_many2one(self, call, relation, rid, ctx):
        """Return local id for a remote (relation, id) or False."""
        if not rid:
            return False
        key = (relation, rid)
        cache = ctx['cache']
        if key in cache:
            return cache[key]
        local = False
        env = self.env
        if relation == 'leads.sources':
            r = call(relation, 'read', [rid], fields=['name', 'digital_lead', 'source'])[0]
            rec = env[relation].search([('name', '=ilike', r['name'])], limit=1)
            if not rec:
                rec = env[relation].create({
                    'name': r['name'], 'digital_lead': r.get('digital_lead'),
                    'source': r.get('source') or False})
                ctx['sources_created'] += 1
            local = rec.id
        elif relation == 'lead.source.campaign':
            r = call(relation, 'read', [rid], fields=['name', 'lead_source_id', 'sequence', 'active'])[0]
            parent = self._map_many2one(call, 'leads.sources', (r['lead_source_id'] or [False])[0], ctx)
            dom = [('name', '=ilike', r['name']), ('lead_source_id', '=', parent or False)]
            rec = env[relation].with_context(active_test=False).search(dom, limit=1)
            if not rec:
                rec = env[relation].create({
                    'name': r['name'], 'lead_source_id': parent or False,
                    'sequence': r.get('sequence') or 10, 'active': r.get('active', True)})
                ctx['campaigns_created'] += 1
            local = rec.id
        elif relation == 'res.users':
            r = call(relation, 'read', [rid], fields=['login', 'name'], context={'active_test': False})[0]
            rec = env[relation].with_context(active_test=False).search([('login', '=', r['login'])], limit=1)
            local = rec.id
        elif relation == 'hr.employee':
            r = call(relation, 'read', [rid], fields=['name', 'work_email'], context={'active_test': False})[0]
            dom = [('name', '=ilike', r['name'])]
            rec = env[relation].with_context(active_test=False).search(dom, limit=1)
            if not rec and r.get('work_email'):
                rec = env[relation].with_context(active_test=False).search(
                    [('work_email', '=ilike', r['work_email'])], limit=1)
            local = rec.id
        elif relation == 'res.company':
            r = call(relation, 'read', [rid], fields=['name'])[0]
            rec = env[relation].search([('name', '=ilike', r['name'])], limit=1)
            local = rec.id or env.company.id
        elif relation in ('course.interested', 'call.responses'):
            r = call(relation, 'read', [rid], fields=['name'])[0]
            if r.get('name'):
                rec = env[relation].search([('name', '=', r['name'])], limit=1) or \
                    env[relation].create({'name': r['name']})
                local = rec.id
        elif relation in env:
            # generic: match by display name if the comodel exists locally
            try:
                r = call(relation, 'read', [rid], fields=['display_name'])[0]
                rec = env[relation].search([('display_name', '=ilike', r['display_name'])], limit=1)
                local = rec.id
            except Exception:
                local = False
        cache[key] = local
        return local

    def _convert_vals(self, call, rvals, rfields, ctx):
        """Convert one remote read() dict into create() vals for leads.logic."""
        Lead = self.env['leads.logic']
        vals = {}
        for fname, rv in rvals.items():
            if fname in SKIP_FIELDS or fname not in Lead._fields:
                continue
            lf = Lead._fields[fname]
            if lf.compute or lf.related or not lf.store or lf.type in ('one2many', 'binary', 'html'):
                continue
            rtype = rfields.get(fname, {}).get('type')
            if rtype != lf.type:
                continue
            if lf.type == 'many2one':
                if not rv:
                    continue
                lid = self._map_many2one(call, lf.comodel_name, rv[0], ctx)
                if lid:
                    vals[fname] = lid
            elif lf.type == 'many2many':
                ids = [self._map_many2one(call, lf.comodel_name, i, ctx) for i in (rv or [])]
                ids = [i for i in ids if i]
                if ids:
                    vals[fname] = [(6, 0, ids)]
            elif lf.type == 'selection':
                if not rv:
                    continue
                keys = {k for k, _l in lf._description_selection(self.env)}
                if rv in keys:
                    vals[fname] = rv
                else:
                    ctx['warnings'].append('%s: value "%s" not in Odoo 19 selection' % (fname, rv))
            elif rv is not False or lf.type == 'boolean':
                vals[fname] = rv
        return vals

    # ------------------------------------------------------------------ #
    def action_import(self):
        self.ensure_one()
        running = self.env['otm.leads.odoo17.import.log'].search([('state', '=', 'running')], order='id')
        if running:
            first = running[0]
            raise UserError(_(
                "Import %(name)s is still running in the background (%(done)s of %(total)s imported).\n"
                "Starting another import now would make the server do the same work twice and can make it "
                "freeze (offline / online).\n\n"
                "Open Import Logs > %(name)s to follow it. If it has stopped, click Resume import there; "
                "if it is an old duplicate, open it and mark it done, then start the new import."
            ) % {'name': first.name, 'done': first.created_count, 'total': first.fetched_count})
        log = self._run_import()
        return {'type': 'ir.actions.act_window', 'res_model': log._name, 'res_id': log.id,
                'view_mode': 'form', 'target': 'current', 'name': _('Import Result')}

    def _run_import(self, log=None, budget=None):
        """Import new leads. First click: ~40s in the foreground, then the rest
        continues automatically in the background (cron) until nothing remains."""
        self.ensure_one()
        resume = bool(log)
        call, info = self._connect()
        Lead = self.env['leads.logic'].with_context(
            otm_odoo17_import=True, tracking_disable=True, mail_create_nolog=True,
            mail_notrigger=True, mail_activity_quick_update=True)
        an = self._analyse(call)
        remote_ids = an['all_ids']
        re_rows = call('lead.re.enquiry', 'search_read', self._reenquiry_domain(), order='id asc') \
            if self.import_reenquiries else []
        rfields = call('leads.logic', 'fields_get', attributes=['type', 'relation', 'store'])
        # Read only STORED fields that also exist locally (computed, non-stored
        # Odoo 17 fields can raise errors on the 17 side and are useless here)
        local_fields = self.env['leads.logic']._fields
        read_fields = sorted(
            f for f, d in rfields.items()
            if d.get('store') and (f in local_fields or f in (
                'lead_owner', 'tele_caller_id', 'lead_creator_id', 'reference_no',
                'create_date', 'write_date', 'name'))
            and d.get('type') not in ('one2many', 'binary', 'html'))
        ctx = {'cache': {}, 'sources_created': 0, 'campaigns_created': 0, 'warnings': []}

        if not resume:
            log = self.env['otm.leads.odoo17.import.log'].create({
                'name': self.env['ir.sequence'].next_by_code('otm.leads.odoo17.import.log') or _('Import'),
                'date_from': self.date_from, 'date_to': self.date_to, 'date_field': self.date_field,
                'fetched_count': len(remote_ids)})
            base_created = base_failed = 0
            dup = len(an['dup_ids'])
            already_n = len(an['already_ids'])
            lines = []
            total_selected = len(remote_ids)
        else:  # continuing an earlier run: keep its totals
            base_created, base_failed = log.created_count, log.failed_count
            dup, already_n = log.duplicate_count, log.already_count
            lines = (log.details or '').splitlines() + ['--- continued in background ---']
            total_selected = log.fetched_count
        created = failed = 0
        todo = an['new_ids']
        if budget is None:
            budget = float(self.env['ir.config_parameter'].sudo().get_param('otm_odoo17.import_time_budget', 10))
        t0 = _time.time()
        truncated = False
        if dup and not resume:
            lines.append('%d lead(s) skipped - phone number already exists in Odoo 19 (ids: %s%s)' % (
                dup, ', '.join(str(i) for i in an['dup_ids'][:50]), ' ...' if dup > 50 else ''))

        for start in range(0, len(todo), BATCH):
            if _time.time() - t0 > budget:
                truncated = True
                break
            chunk = todo[start:start + BATCH]
            rows = call('leads.logic', 'read', chunk, fields=read_fields)
            if self.import_children:
                self._prefetch_children(call, chunk, ctx)
            for row in rows:
                rid = row['id']
                try:
                    with self.env.cr.savepoint():
                        vals = self._convert_vals(call, row, rfields, ctx)
                        phone = (vals.get('phone_number') or '').replace(' ', '')
                        if phone:
                            existing = Lead.sudo().search(
                                [('phone_number', 'like', '%' + phone[-10:])], limit=1)
                            if existing:
                                dup += 1
                                lines.append('#%s %s (%s): duplicate phone of %s - skipped' % (
                                    rid, row.get('name'), phone, existing.reference_no))
                                continue
                        owner = self._map_many2one(call, 'hr.employee', (row.get('lead_owner') or [0])[0], ctx)
                        caller = self._map_many2one(call, 'res.users', (row.get('tele_caller_id') or [0])[0], ctx)
                        creator = self._map_many2one(call, 'res.users', (row.get('lead_creator_id') or [0])[0], ctx)
                        vals.setdefault('company_id', self.env.company.id)
                        vals.update({
                            'odoo17_lead_id': rid,
                            'odoo17_import_log_id': log.id,
                            'lead_creator_id': creator or self.env.uid,
                            'reference_no': row.get('reference_no') if row.get('reference_no') and not
                            Lead.sudo().search_count([('reference_no', '=', row['reference_no'])]) else _('New'),
                        })
                        lead = Lead.create(vals)
                        post = {}
                        if owner:
                            post['lead_owner'] = owner
                        if caller:
                            post['tele_caller_id'] = caller
                        if post:
                            lead.with_context(skip_assignment_history=True).write(post)
                        # keep original creation / update timestamps
                        self.env.cr.execute(
                            "UPDATE leads_logic SET create_date=%s, write_date=%s WHERE id=%s",
                            (row['create_date'], row['write_date'], lead.id))
                        if self.import_children:
                            self._import_children(call, Lead.browse(lead.id), rid, ctx)
                        if self.import_chatter:
                            self._import_chatter(call, lead, rid, ctx)
                        created += 1
                except Exception as e:
                    failed += 1
                    lines.append('#%s %s: FAILED - %s' % (rid, row.get('name'), str(e).strip()[:300]))
                    _logger.warning('Odoo17 import failed for lead %s: %s', rid, e)
            log.write({'created_count': base_created + created, 'failed_count': base_failed + failed,
                       'last_activity': fields.Datetime.now()})
            self.env.cr.commit()  # keep progress on long runs
            self.env.invalidate_all()  # free ORM cache so memory stays flat on big imports
            _time.sleep(0.3)  # let the web workers breathe

        remaining = len(todo) - created - failed if truncated else 0
        created_t, failed_t = base_created + created, base_failed + failed
        if re_rows and not truncated:
            r_ok, r_skip, r_fail = self._import_reenquiries(call, re_rows, ctx, lines)
            lines.append('Re-Attempts: %d created, %d skipped, %d failed.' % (r_ok, r_skip, r_fail))
            failed_t += r_fail

        if ctx['warnings']:
            lines.append('--- Warnings (first 50) ---')
            lines.extend(sorted(set(ctx['warnings']))[:50])
        summary = ['SELECTED %d  =  IMPORTED %d  +  ALREADY IMPORTED %d  +  PHONE DUPLICATE %d  +  FAILED %d%s' % (
            total_selected, created_t, already_n, dup, failed_t,
            ('  +  REMAINING %d' % remaining) if truncated else '')]
        if truncated:
            summary.append('The rest is importing automatically in the background - refresh this page '
                           'in a minute to see the numbers grow. Nothing else to click.')
        # strip an older summary line when we rewrite it
        body = [l for l in lines if l and not l.startswith('SELECTED ')]
        log.write({
            'fetched_count': total_selected, 'created_count': created_t, 'duplicate_count': dup,
            'already_count': already_n, 'remaining_count': remaining, 'failed_count': failed_t,
            'campaigns_created': (log.campaigns_created or 0) + ctx['campaigns_created'],
            'sources_created': (log.sources_created or 0) + ctx['sources_created'],
            'details': '\n'.join(summary + [''] + body),
            'state': 'running' if truncated else 'done',
            'last_activity': fields.Datetime.now(),
            'params': self._bg_params() if truncated else False,
        })
        if truncated:
            self.env.cr.commit()
            cron = self.env.ref('custom_leads_19.cron_otm_leads_odoo17_import', raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()
        return log

    def _bg_params(self):
        import json
        return json.dumps({
            'date_from': str(self.date_from), 'date_to': str(self.date_to), 'date_field': self.date_field,
            'import_children': self.import_children, 'import_chatter': self.import_chatter,
            'import_reenquiries': self.import_reenquiries,
            'campaign_remote_ids': self.campaign_option_ids.mapped('remote_id'),
        })

    # ------------------------------------------------------------------ #
    def _import_reenquiries(self, call, rows, ctx, lines):
        """Odoo 17 lead.re.enquiry -> Odoo 19 otomater.lead.reattempt."""
        env = self.env
        Lead = env['leads.logic'].sudo()
        Re = env['otomater.lead.reattempt'].with_context(
            otm_odoo17_import=True, tracking_disable=True, mail_create_nolog=True, mail_notrigger=True)
        status_map = {'pending': 'pending_review', 'approved': 'approved',
                      'rejected': 'rejected', 'merged': 'assigned'}
        ok = skip = fail = 0
        for r in rows:
            try:
                with env.cr.savepoint():
                    if Re.sudo().search_count([('odoo17_reenquiry_id', '=', r['id'])]):
                        skip += 1
                        continue
                    rlead = (r.get('lead_id') or [0])[0]
                    lead = Lead.search([('odoo17_lead_id', '=', rlead)], limit=1)
                    if not lead:
                        ld = call('leads.logic', 'read', [rlead], fields=['phone_number'])
                        ph = ((ld and ld[0].get('phone_number')) or '').replace(' ', '')
                        if ph:
                            lead = Lead.search([('phone_number', 'like', '%' + ph[-10:])], limit=1)
                    if not lead:
                        skip += 1
                        lines.append('Re-Attempt #%s: lead #%s not found in Odoo 19 - skipped' % (r['id'], rlead))
                        continue
                    m2o = lambda rel, v: self._map_many2one(call, rel, (v or [0])[0], ctx) if v else False
                    req_uid = m2o('res.users', r.get('created_by'))
                    req_emp = env['hr.employee'].search([('user_id', '=', req_uid)], limit=1).id if req_uid else False
                    course_ids = []
                    for nm in (r.get('course_interested') or '').split(','):
                        nm = nm.strip()
                        if nm:
                            c = env['course.interested'].search([('name', '=', nm)], limit=1) or \
                                env['course.interested'].create({'name': nm})
                            course_ids.append(c.id)
                    vals = {
                        'lead_id': lead.id,
                        'existing_owner_id': lead.lead_owner.id or False,
                        'requested_owner_id': req_emp,
                        'old_source_id': m2o('leads.sources', r.get('old_source_id')),
                        'source_id': m2o('leads.sources', r.get('leads_source')),
                        'course_id': [(6, 0, course_ids)] if course_ids else False,
                        'remarks': r.get('remarks') or False,
                        'mobile': lead.phone_number,
                        'email': lead.email_address or False,
                        'duplicate_type': 'phone',
                        'review_status': status_map.get(r.get('review_state'), 'pending_review'),
                        'rejection_reason': (r.get('review_notes') or False)
                        if r.get('review_state') == 'rejected' else False,
                        'odoo17_reenquiry_id': r['id'],
                    }
                    if r.get('enquiry_date'):
                        vals['request_date'] = r['enquiry_date'] + ' 00:00:00'
                    if r.get('reviewed_on'):
                        vals['review_date'] = r['reviewed_on']
                    Re.create({k: v for k, v in vals.items() if v is not False or k == 'review_status'})
                    ok += 1
            except Exception as e:
                fail += 1
                lines.append('Re-Attempt #%s: FAILED - %s' % (r['id'], str(e).strip()[:250]))
        env.cr.commit()
        return ok, skip, fail

    # ------------------------------------------------------------------ #
    def _prefetch_children(self, call, remote_ids, ctx):
        """One Odoo 17 call per child model for a whole batch of leads (instead of one per lead).
        The rows are exactly the ones the per-lead calls would have returned."""
        env = self.env
        specs = {
            'lead.response': ['user_id', 'comment', 'response_time'],
            'lead.call.log': ['user_id', 'call_time', 'remarks', 'call_uuid', 'caller_number',
                              'call_status', 'duration', 'recording_url', 'call_type'],
            'lead.followup': ['user_id', 'next_followup_date', 'remarks', 'phone_number', 'status'],
            'lead.quality.history': ['lead_quality', 'user_id', 'change_date'],
        }
        ctx['pf'] = {}
        ctx['pf_ah'] = None
        for model, flds in specs.items():
            if model not in env:
                continue
            avail = [f for f in flds if f in env[model]._fields]
            try:
                rows = call(model, 'search_read', [('lead_id', 'in', remote_ids)],
                            fields=avail + ['create_date', 'lead_id'], order='id asc')
            except Exception:
                continue          # falls back to the per-lead call, which reports the warning
            grouped = {}
            for r in rows:
                lid = r['lead_id'][0] if isinstance(r.get('lead_id'), (list, tuple)) else r.get('lead_id')
                grouped.setdefault(lid, []).append(r)
            ctx['pf'][model] = grouped
        spec = self._remote_assignment_model(call, ctx)
        if spec:
            read_f = list(spec['fields'].values()) + ['create_date', 'lead_id']
            try:
                rows = call(spec['model'], 'search_read', [('lead_id', 'in', remote_ids)],
                            fields=read_f, order='id asc')
                grouped = {}
                for r in rows:
                    lid = r['lead_id'][0] if isinstance(r.get('lead_id'), (list, tuple)) else r.get('lead_id')
                    grouped.setdefault(lid, []).append(r)
                ctx['pf_ah'] = grouped
            except Exception:
                ctx['pf_ah'] = None

    def _import_children(self, call, lead, remote_lead_id, ctx):
        env = self.env
        specs = {
            'lead.response': ['user_id', 'comment', 'response_time'],
            'lead.call.log': ['user_id', 'call_time', 'remarks', 'call_uuid', 'caller_number',
                              'call_status', 'duration', 'recording_url', 'call_type'],
            'lead.followup': ['user_id', 'next_followup_date', 'remarks', 'phone_number', 'status'],
            'lead.quality.history': ['lead_quality', 'user_id', 'change_date'],
        }
        for model, flds in specs.items():
            if model not in env:
                continue
            Local = env[model]
            avail = [f for f in flds if f in Local._fields]
            try:
                pf = ctx.get('pf', {}).get(model)
                if pf is not None:           # rows for the whole batch were fetched in one call
                    rows = pf.get(remote_lead_id, [])
                else:
                    rows = call(model, 'search_read', [('lead_id', '=', remote_lead_id)],
                                fields=avail + ['create_date'])
            except Exception as e:
                ctx['warnings'].append('%s could not be read from Odoo 17: %s' % (model, str(e)[:120]))
                continue
            for r in rows:
                vals = {'lead_id': lead.id}
                for f in avail:
                    lf = Local._fields[f]
                    v = r.get(f)
                    if lf.type == 'many2one':
                        v = self._map_many2one(call, lf.comodel_name, (v or [0])[0], ctx) if v else False
                        if not v and f == 'user_id':
                            v = False
                    elif lf.type == 'selection' and v:
                        if v not in {k for k, _l in lf._description_selection(env)}:
                            continue
                    if v is False and lf.type != 'boolean':
                        continue
                    vals[f] = v
                rec = Local.create(vals)
                if r.get('create_date'):
                    env.cr.execute('UPDATE "%s" SET create_date=%%s WHERE id=%%s' % Local._table,
                                   (r['create_date'], rec.id))
        self._import_assignment_history(call, lead, [remote_lead_id], ctx)
        # response-time columns were computed before the original create date was restored
        lead.invalidate_recordset()
        if hasattr(lead, '_compute_response_times'):
            lead._compute_response_times()

    # ------------------------------------------------------------------ #
    #  Assignment history - copied exactly as it was in Odoo 17
    # ------------------------------------------------------------------ #
    _AH_ALIASES = {
        'owner': ('owner_id', 'lead_owner', 'lead_owner_id', 'employee_id', 'officer_id'),
        'date': ('assigned_date', 'assign_date', 'date', 'assigned_on'),
        'by': ('assigned_by', 'assigned_by_id', 'user_id'),
    }

    def _remote_assignment_model(self, call, ctx):
        """Find the Odoo 17 model holding the assignment history and the field names to read."""
        if 'ah_spec' in ctx:
            return ctx['ah_spec']
        spec = None
        names = ['lead.assignment.history']
        try:
            found = call('ir.model', 'search_read',
                         [('model', 'ilike', 'assign'), ('model', 'ilike', 'hist')], fields=['model'])
            names += [m['model'] for m in found if m['model'] not in names]
        except Exception:
            pass
        for name in names:
            try:
                fg = call(name, 'fields_get', attributes=['type', 'relation', 'store'])
            except Exception:
                continue
            if 'lead_id' not in fg:
                continue
            pick = {}
            for key, aliases in self._AH_ALIASES.items():
                for a in aliases:
                    if a in fg and fg[a].get('store', True):
                        pick[key] = a
                        break
            if 'owner' in pick:
                spec = {'model': name, 'fields': pick, 'types': fg}
                break
        if not spec:
            ctx['warnings'].append('No assignment history model found in Odoo 17 - history not imported.')
        ctx['ah_spec'] = spec
        return spec

    def _import_assignment_history(self, call, lead, remote_ids, ctx, replace=False):
        """Copy the Odoo 17 assignment history rows of `remote_ids` (remote lead ids) onto `lead`.
        Dates, officers and 'assigned by' are kept as they were. Nothing is invented: a lead without
        history in Odoo 17 gets none."""
        spec = self._remote_assignment_model(call, ctx)
        if not spec:
            return 0
        pick, fg = spec['fields'], spec['types']
        read_f = list(pick.values()) + ['create_date']
        try:
            pf = ctx.get('pf_ah')
            if pf is not None and len(remote_ids) == 1 and not replace:
                rows = pf.get(remote_ids[0], [])
            else:
                rows = call(spec['model'], 'search_read', [('lead_id', 'in', remote_ids)],
                            fields=read_f, order='id asc')
        except Exception as e:
            ctx['warnings'].append('Assignment history could not be read: %s' % str(e)[:120])
            return 0
        Hist = self.env['lead.assignment.history'].sudo()
        if replace:
            Hist.search([('lead_id', '=', lead.id)]).unlink()
        n = 0
        for r in rows:
            def m2o(key, relation_default):
                f = pick.get(key)
                v = r.get(f) if f else False
                if not v:
                    return False
                rel = fg[f].get('relation') or relation_default
                return self._map_many2one(call, rel, v[0] if isinstance(v, (list, tuple)) else v, ctx)
            owner = m2o('owner', 'hr.employee')
            if not owner:
                continue
            when = r.get(pick['date']) if 'date' in pick else False
            vals = {
                'lead_id': lead.id,
                'owner_id': owner,
                'assigned_date': when or r.get('create_date') or fields.Datetime.now(),
            }
            by = m2o('by', 'res.users')
            if by:
                vals['assigned_by'] = by
            Hist.create(vals)
            n += 1
        return n

    def action_backfill_assignment_history(self):
        """Replace the assignment history of leads already imported from Odoo 17 with the exact
        Odoo 17 history (use this for leads imported before assignment history was supported)."""
        self.ensure_one()
        call, label = self._connect()
        ctx = {'cache': {}, 'sources_created': 0, 'campaigns_created': 0, 'warnings': []}
        Lead = self.env['leads.logic'].sudo()
        leads = Lead.search([('odoo17_lead_id', '>', 0)])
        done = rows = 0
        start = _time.time()
        for lead in leads:
            if _time.time() - start > 100:
                break
            try:
                with self.env.cr.savepoint():
                    rows += self._import_assignment_history(call, lead, [lead.odoo17_lead_id], ctx, replace=True)
                    lead._compute_response_times()
                    done += 1
            except Exception as e:
                ctx['warnings'].append('Lead %s: %s' % (lead.reference_no, str(e)[:100]))
        self.env.cr.commit()
        msg = _('%(d)s of %(t)s imported leads processed, %(r)s assignment history rows copied.') % {
            'd': done, 't': len(leads), 'r': rows}
        if done < len(leads):
            msg += ' ' + _('Click again to continue (time limit reached).')
        if ctx['warnings']:
            msg += '\n' + '\n'.join(ctx['warnings'][:5])
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Assignment history'), 'message': msg, 'sticky': True, 'type': 'success'}}

    def _import_chatter(self, call, lead, remote_lead_id, ctx):
        Msg = self.env['mail.message']
        rows = call('mail.message', 'search_read',
                    [('model', '=', 'leads.logic'), ('res_id', '=', remote_lead_id),
                     ('message_type', 'in', ['comment', 'notification']), ('body', '!=', False)],
                    fields=['body', 'date', 'author_id', 'message_type', 'subject'], order='id asc')
        for r in rows:
            if not (r.get('body') or '').strip():
                continue
            author = False
            if r.get('author_id'):
                name = r['author_id'][1]
                author = self.env['res.partner'].search([('name', '=', name)], limit=1).id
            Msg.create({
                'model': 'leads.logic', 'res_id': lead.id, 'body': fix_escaped_html(r['body']),
                'date': r['date'], 'author_id': author or False,
                'message_type': 'comment', 'subtype_id': self.env.ref('mail.mt_note').id,
                'subject': r.get('subject') or False,
            })


class OtomaterLeadReattemptOdoo17(models.Model):
    _inherit = 'otomater.lead.reattempt'

    odoo17_reenquiry_id = fields.Integer(
        string='Odoo 17 Re-Enquiry ID', index=True, copy=False, readonly=True)
