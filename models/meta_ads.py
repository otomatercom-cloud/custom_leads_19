# -*- coding: utf-8 -*-
"""Meta Ads performance: daily spend per campaign pulled from the Meta Marketing API, joined (by campaign name)
with the Meta leads in Odoo, for the Meta Ads dashboard (leads per day per campaign, spend, CPL, cost per admission)."""
import json
import logging
import re
from datetime import timedelta

import requests

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)
P = 'custom_leads_19.meta_ads_'
GRAPH = 'https://graph.facebook.com/%s/act_%s/insights'
DASH_GROUPS = ('custom_leads_19.group_super_admin', 'custom_leads_19.group_lead_manager',
               'custom_leads_19.group_lead_digital_head', 'custom_leads_19.group_lead_digital_team')
SYNC_GROUPS = ('custom_leads_19.group_super_admin', 'custom_leads_19.group_lead_manager',
               'custom_leads_19.group_lead_digital_head')


def _key(name):
    return re.sub(r'\s+', ' ', (name or '')).strip().lower()


class OtmMetaSpend(models.Model):
    _name = 'otm.meta.spend'
    _description = 'Meta ads daily spend'
    _order = 'date desc, campaign_name'

    date = fields.Date(required=True, index=True)
    campaign_id = fields.Char(string='Meta campaign ID', index=True)
    campaign_name = fields.Char(string='Campaign', required=True)
    account_id = fields.Char(string='Ad account')
    spend = fields.Float(digits=(16, 2))
    impressions = fields.Integer()
    clicks = fields.Integer()
    meta_leads = fields.Integer(string='Leads (per Meta)')

    _day_camp_uniq = models.Constraint('UNIQUE(date, campaign_id, account_id)', 'One row per day, campaign and account.')

    # ── settings ───────────────────────────────────────────────────────
    @api.model
    def _p(self, key, default=''):
        return (self.env['ir.config_parameter'].sudo().get_param(P + key) or '').strip() or default

    # ── sync from the Marketing API ────────────────────────────────────
    @api.model
    def sync_meta_ads(self, days=None):
        """Pull daily campaign insights for the last `days` days. Returns the number of rows written."""
        if not any(self.env.user.has_group(g) for g in SYNC_GROUPS) and not self.env.su:
            raise AccessError(_('Only Manager, Super Admin or Digital Head can sync Meta ads.'))
        token = self._p('token')
        accounts = [a.replace('act_', '') for a in re.split(r'[,\s;]+', self._p('accounts')) if a]
        if not token or not accounts:
            raise UserError(_('Add the Meta access token and ad account ID in Settings > Leads > Meta Ads first.'))
        ver = self._p('version', 'v21.0')
        days = max(1, min(int(days or self._p('days', '7') or 7), 93))
        until = fields.Date.context_today(self)
        since = until - timedelta(days=days - 1)
        rows = 0
        for acc in accounts:
            url = GRAPH % (ver, acc)
            params = {'level': 'campaign', 'fields': 'campaign_id,campaign_name,spend,impressions,clicks,actions',
                      'time_increment': 1, 'limit': 500, 'access_token': token,
                      'time_range': json.dumps({'since': str(since), 'until': str(until)})}
            while url:
                try:
                    r = requests.get(url, params=params, timeout=60)
                except requests.RequestException as e:
                    raise UserError(_('Could not reach Meta: %s') % str(e)[:200])
                if r.status_code != 200:
                    try:
                        msg = r.json().get('error', {}).get('message') or r.text
                    except ValueError:
                        msg = r.text
                    raise UserError(_('Meta error %(c)s for account %(a)s: %(m)s') % {'c': r.status_code, 'a': acc, 'm': msg[:300]})
                js = r.json()
                for row in js.get('data', []):
                    rows += self._upsert_row(acc, row)
                url, params = (js.get('paging') or {}).get('next'), None
        return rows

    @api.model
    def _upsert_row(self, acc, row):
        acts = {a.get('action_type'): a.get('value') for a in row.get('actions') or []}
        leads = acts.get('lead', acts.get('onsite_conversion.lead_grouped', 0))
        vals = {'date': row.get('date_start'), 'campaign_id': row.get('campaign_id') or '', 'account_id': acc,
                'campaign_name': row.get('campaign_name') or row.get('campaign_id') or '-',
                'spend': float(row.get('spend') or 0), 'impressions': int(float(row.get('impressions') or 0)),
                'clicks': int(float(row.get('clicks') or 0)), 'meta_leads': int(float(leads or 0))}
        rec = self.sudo().search([('date', '=', vals['date']), ('campaign_id', '=', vals['campaign_id']),
                                  ('account_id', '=', acc)], limit=1)
        if rec:
            rec.write(vals)
        else:
            self.sudo().create(vals)
        return 1

    @api.model
    def cron_meta_ads_sync(self):
        if self._p('enabled') not in ('True', 'true', '1'):
            return
        try:
            self.sudo().sync_meta_ads(days=3)
        except Exception as e:  # noqa: BLE001
            _logger.warning('Meta ads sync failed: %s', e)

    def action_sync_now(self):
        n = self.sync_meta_ads()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _('Meta ads'), 'message': _('%s day/campaign rows updated.') % n, 'type': 'success'}}


class ResConfigSettingsMetaAds(models.TransientModel):
    _inherit = 'res.config.settings'

    meta_ads_enabled = fields.Boolean(string='Sync Meta ad spend automatically', config_parameter=P + 'enabled')
    meta_ads_token = fields.Char(string='Meta access token', config_parameter=P + 'token',
                                 help='A System User token with the ads_read permission.')
    meta_ads_accounts = fields.Char(string='Ad account ID(s)', config_parameter=P + 'accounts',
                                    help='Numbers only (without act_). Several accounts: separate with commas.')
    meta_ads_version = fields.Char(string='Graph API version', config_parameter=P + 'version', default='v21.0')
    meta_ads_days = fields.Integer(string='Days to refresh on a manual sync', config_parameter=P + 'days', default=7)


class LeadsLogicMetaDash(models.Model):
    _inherit = 'leads.logic'

    @api.model
    def get_meta_dashboard(self, date_from=False, date_to=False):
        user = self.env.user
        if not any(user.has_group(g) for g in DASH_GROUPS) and not user.has_group('base.group_system'):
            raise AccessError(_('Meta Ads dashboard is for Manager, Super Admin and the Digital team.'))
        self = self.with_context(tz=self._rd_tzname())
        today = fields.Date.context_today(self)
        d2 = fields.Date.to_date(date_to) if date_to else today
        d1 = fields.Date.to_date(date_from) if date_from else d2 - timedelta(days=6)
        if d1 > d2:
            d1, d2 = d2, d1
        d1 = max(d1, d2 - timedelta(days=92))
        days = [d1 + timedelta(days=i) for i in range((d2 - d1).days + 1)]
        idx = {str(d): i for i, d in enumerate(days)}
        start, end = self._rd_utc(d1), self._rd_utc(d2, end=True)
        Lead = self.sudo()
        base = [('leads_source.name', 'ilike', 'meta'), ('create_date', '>=', start), ('create_date', '<', end)]
        rows = {}

        def row(name, hiring=False):
            k = _key(name)
            if k not in rows:
                rows[k] = {'name': name, 'hiring': hiring, 'leads': 0, 'good': 0, 'adm': 0, 'spend': 0.0,
                           'impressions': 0, 'clicks': 0, 'meta_leads': 0,
                           'daily': [0] * len(days), 'daily_spend': [0.0] * len(days)}
            return rows[k]

        def camp_name(c):
            return c.name if c else '(no campaign)'

        for c, n in Lead._read_group(base, ['source_campaign_id'], ['__count']):
            r = row(camp_name(c), bool(c and c.is_hiring))
            r['leads'] += n
        for c, n in Lead._read_group(base + [('lead_quality', 'in', ['hot', 'warm'])], ['source_campaign_id'], ['__count']):
            row(camp_name(c))['good'] += n
        adm_dom = ['|', ('admission_status', '=', True), ('lead_quality', 'in', ['admission', 'logic_students'])]
        for c, n in Lead._read_group(base + adm_dom, ['source_campaign_id'], ['__count']):
            row(camp_name(c))['adm'] += n
        tot_daily = [0] * len(days)
        for c, day, n in Lead._read_group(base, ['source_campaign_id', 'create_date:day'], ['__count']):
            i = idx.get(str(day.date() if hasattr(day, 'date') else day))
            if i is not None:
                row(camp_name(c))['daily'][i] += n
                tot_daily[i] += n

        spend_rows = self.env['otm.meta.spend'].sudo().search_read(
            [('date', '>=', d1), ('date', '<=', d2)], ['date', 'campaign_name', 'spend', 'impressions', 'clicks', 'meta_leads'])
        tot_spend = [0.0] * len(days)
        last_sync = False
        for s in spend_rows:
            r = row(s['campaign_name'])
            r['spend'] += s['spend']
            r['impressions'] += s['impressions']
            r['clicks'] += s['clicks']
            r['meta_leads'] += s['meta_leads']
            i = idx.get(str(s['date']))
            if i is not None:
                r['daily_spend'][i] += s['spend']
                tot_spend[i] += s['spend']
        last = self.env['otm.meta.spend'].sudo().search([], order='write_date desc', limit=1)
        if last:
            last_sync = fields.Datetime.to_string(last.write_date)

        out = []
        for r in rows.values():
            r['spend'] = round(r['spend'], 2)
            r['cpl'] = round(r['spend'] / r['leads'], 2) if r['leads'] and r['spend'] else None
            r['cpa'] = round(r['spend'] / r['adm'], 2) if r['adm'] and r['spend'] else None
            r['ctr'] = round(100.0 * r['clicks'] / r['impressions'], 2) if r['impressions'] else None
            r['daily_spend'] = [round(x, 2) for x in r['daily_spend']]
            out.append(r)
        out.sort(key=lambda r: (-r['leads'], -r['spend'], r['name']))
        tot = {k: sum(r[k] for r in out) for k in ('leads', 'good', 'adm', 'impressions', 'clicks', 'meta_leads')}
        tot['spend'] = round(sum(r['spend'] for r in out), 2)
        tot['cpl'] = round(tot['spend'] / tot['leads'], 2) if tot['leads'] and tot['spend'] else None
        tot['cpa'] = round(tot['spend'] / tot['adm'], 2) if tot['adm'] and tot['spend'] else None
        tot['ctr'] = round(100.0 * tot['clicks'] / tot['impressions'], 2) if tot['impressions'] else None
        return {
            'from': str(d1), 'to': str(d2), 'days': [str(d) for d in days], 'rows': out, 'totals': tot,
            'daily_leads': tot_daily, 'daily_spend': [round(x, 2) for x in tot_spend],
            'configured': bool(self.env['otm.meta.spend']._p('token') and self.env['otm.meta.spend']._p('accounts')),
            'range': {'s': fields.Datetime.to_string(start), 'e': fields.Datetime.to_string(end)},
            'last_sync': last_sync, 'can_sync': any(user.has_group(g) for g in SYNC_GROUPS),
        }
