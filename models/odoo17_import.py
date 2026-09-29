import logging
import xmlrpc.client
from datetime import datetime, time

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BATCH = 100

# Never copied from Odoo 17 (handled explicitly, technical or unsafe)
SKIP_FIELDS = {
    'id', 'reference_no', 'odoo17_lead_id', 'message_ids', 'message_follower_ids',
    'activity_ids', 'website_message_ids', 'create_uid', 'write_uid', 'create_date',
    'write_date', 'display_name', 'lead_owner', 'tele_caller_id', 'lead_creator_id',
    'student_id', 'adm_id', 'sample', 'progress_html', 'masked_phone', 'show_phone',
}

# One2many children imported in a dedicated step: (remote model, local model, link field)
CHILD_MODELS = ('lead.response', 'lead.call.log', 'lead.followup', 'lead.quality.history')


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
    duplicate_count = fields.Integer(string='Skipped (Duplicate)', readonly=True)
    failed_count = fields.Integer(string='Failed', readonly=True)
    campaigns_created = fields.Integer(string='Campaigns Created', readonly=True)
    sources_created = fields.Integer(string='Sources Created', readonly=True)
    details = fields.Text(string='Details', readonly=True)
    lead_ids = fields.One2many('leads.logic', 'odoo17_import_log_id', string='Imported Leads')


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
        string='Import Responses, Call Logs, Follow-ups & Quality History', default=True)
    import_chatter = fields.Boolean(
        string='Import Chatter Messages', default=False,
        help='Copies comments/notes from the Odoo 17 chatter. Slower.')
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

    def action_test_connection(self):
        self.ensure_one()
        call, info = self._connect()
        count = call('leads.logic', 'search_count', self._remote_domain())
        self.write({'preview_count': count, 'connection_info': info})
        return self._reopen()

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
        call, info = self._connect()
        Lead = self.env['leads.logic'].with_context(
            otm_odoo17_import=True, tracking_disable=True, mail_create_nolog=True,
            mail_notrigger=True, mail_activity_quick_update=True)
        domain = self._remote_domain()
        remote_ids = call('leads.logic', 'search', domain, order='id asc')
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

        log = self.env['otm.leads.odoo17.import.log'].create({
            'name': self.env['ir.sequence'].next_by_code('otm.leads.odoo17.import.log') or _('Import'),
            'date_from': self.date_from, 'date_to': self.date_to, 'date_field': self.date_field,
            'fetched_count': len(remote_ids)})
        created = dup = failed = 0
        lines = []

        already = set(Lead.search([('odoo17_lead_id', 'in', remote_ids)]).mapped('odoo17_lead_id'))
        todo = [i for i in remote_ids if i not in already]
        dup += len(already)
        if already:
            lines.append('%d lead(s) already imported earlier - skipped.' % len(already))

        for start in range(0, len(todo), BATCH):
            chunk = todo[start:start + BATCH]
            rows = call('leads.logic', 'read', chunk, fields=read_fields)
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
            self.env.cr.commit()  # keep progress on long runs

        if ctx['warnings']:
            lines.append('--- Warnings (first 50) ---')
            lines.extend(sorted(set(ctx['warnings']))[:50])
        log.write({
            'created_count': created, 'duplicate_count': dup, 'failed_count': failed,
            'campaigns_created': ctx['campaigns_created'], 'sources_created': ctx['sources_created'],
            'details': '\n'.join(lines),
        })
        return {'type': 'ir.actions.act_window', 'res_model': log._name, 'res_id': log.id,
                'view_mode': 'form', 'target': 'current', 'name': _('Import Result')}

    # ------------------------------------------------------------------ #
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
                rows = call(model, 'search_read', [('lead_id', '=', remote_lead_id)], fields=avail + ['create_date'])
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
                'model': 'leads.logic', 'res_id': lead.id, 'body': r['body'],
                'date': r['date'], 'author_id': author or False,
                'message_type': 'comment', 'subtype_id': self.env.ref('mail.mt_note').id,
                'subject': r.get('subject') or False,
            })
