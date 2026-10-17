# -*- coding: utf-8 -*-
"""Lead Qualities and Stage Categories, managed from the UI (Lead Management Settings > Configuration).

`leads.logic.lead_quality` and `lead_stage_category` stay Selection fields (so every existing domain, report and
dashboard keeps working) but their option lists are now read from these two tables. The built-in values are
`is_system` records: their label, emoji, stage and order can be edited, but the code is locked and they cannot be
deleted because the module's rules (pool, reassign, admission, ...) refer to them by code."""
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

DEFAULT_QUALITY = [
    ('new', '🆕  New'), ('first_attempt', '🎯 First Attempt'), ('waiting_for_admission', '⏳  Waiting for Admission'),
    ('admission', '🎓  Admission'), ('hot', '🔥  Hot'), ('warm', '🌞  Warm'), ('cold', '❄️  Cold'),
    ('bad_lead', '⚠️  Language Barrier'), ('crash_lead', '💥  Crash Lead'),
    ('not_responding', '🔕  Ringing Not Responding'), ('call_later', '📞  Call Later'),
    ('may_be_later', '🔔 May Be Later'), ('follow_up', '⏰  Follow Up'), ('not_reachable', '🚫  Not Reachable'),
    ('logic_students', '🏫 Logic Students'), ('joined_other_institute', '🏫 Joined Other Institute'),
    ('wrong_number', '📵 Wrong number'), ('not_enquiry', '🛑 Not Enquiry'), ('not_interested', 'Not Interested'),
]
DEFAULT_STAGE = [
    ('funnel', 'FUNNEL'), ('prospects', 'PROSPECTS'), ('rnr_dnp', 'RNR / DNP'), ('admission_done', 'ADMISSION DONE'),
    ('re_try', 'RE-TRY'), ('alumni', 'ALUMNI'), ('junk', 'JUNK'),
]
DEFAULT_MAP = {
    'hot': 'prospects', 'warm': 'prospects', 'cold': 'prospects', 'call_later': 'prospects',
    'may_be_later': 'prospects', 'waiting_for_admission': 'prospects',
    'new': 'funnel', 'first_attempt': 'funnel', 'follow_up': 'funnel',
    'not_interested': 're_try', 'bad_lead': 're_try', 'crash_lead': 're_try', 'joined_other_institute': 're_try',
    'not_responding': 'rnr_dnp', 'not_reachable': 'rnr_dnp',
    'admission': 'admission_done', 'converted': 'admission_done',
    'logic_students': 'alumni', 'wrong_number': 'junk', 'not_enquiry': 'junk',
}


def _slug(text):
    s = re.sub(r'[^a-z0-9]+', '_', (text or '').lower()).strip('_')
    return s or 'x'


class LeadStageCategory(models.Model):
    _name = 'lead.stage.category'
    _description = 'Lead Stage Category'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=False)
    code = fields.Char(copy=False, index=True,
                       help='Technical key. Generated from the name; cannot be changed after it is saved.')
    sequence = fields.Integer(default=100)
    is_system = fields.Boolean(readonly=True, copy=False)
    quality_ids = fields.One2many('lead.quality.config', 'stage_id', string='Lead Qualities')
    quality_count = fields.Integer(compute='_compute_quality_count')

    _code_uniq = models.Constraint('unique(code)', 'This stage code already exists.')

    @api.depends('quality_ids')
    def _compute_quality_count(self):
        for rec in self:
            rec.quality_count = len(rec.quality_ids)

    @api.model
    def get_selection(self):
        try:
            recs = self.sudo().search([])
            if recs:
                return [(r.code, r.name) for r in recs]
        except Exception:  # noqa: BLE001  (table not created yet while the module installs)
            pass
        return list(DEFAULT_STAGE)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                base = _slug(vals.get('name'))
                code, n = base, 1
                while self.sudo().search_count([('code', '=', code)]):
                    n += 1
                    code = '%s_%s' % (base, n)
                vals['code'] = code
        return super().create(vals_list)

    def write(self, vals):
        if 'code' in vals and any(r.code != vals['code'] for r in self):
            raise UserError(_('The stage code cannot be changed.'))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.is_system:
                raise UserError(_('"%s" is a built-in stage and cannot be deleted.') % rec.name)
            if rec.quality_ids:
                raise UserError(_('Move the lead qualities of "%s" to another stage first.') % rec.name)
        return super().unlink()


class LeadQualityConfig(models.Model):
    _name = 'lead.quality.config'
    _description = 'Lead Quality'
    _order = 'sequence, id'

    name = fields.Char(string='Label', required=True,
                       help='Shown to the officers, e.g. "🔥  Hot". You can start it with an emoji.')
    code = fields.Char(copy=False, index=True,
                       help='Technical key. Generated from the label; cannot be changed after it is saved.')
    stage_id = fields.Many2one('lead.stage.category', string='Stage Category', required=True, ondelete='restrict',
                               help='The pipeline stage that leads with this quality belong to.')
    sequence = fields.Integer(default=100)
    is_system = fields.Boolean(readonly=True, copy=False)
    lead_count = fields.Integer(compute='_compute_lead_count', string='Leads')

    _code_uniq = models.Constraint('unique(code)', 'This quality code already exists.')

    def _compute_lead_count(self):
        data = self.env['leads.logic'].sudo()._read_group(
            [('lead_quality', 'in', self.mapped('code'))], ['lead_quality'], ['__count'])
        counts = {q: c for q, c in data}
        for rec in self:
            rec.lead_count = counts.get(rec.code, 0)

    @api.model
    def get_selection(self):
        try:
            recs = self.sudo().search([])
            if recs:
                return [(r.code, r.name) for r in recs]
        except Exception:  # noqa: BLE001
            pass
        return list(DEFAULT_QUALITY)

    @api.model
    def stage_map(self):
        """{quality code: stage code}"""
        try:
            recs = self.sudo().search([])
            if recs:
                m = {r.code: r.stage_id.code for r in recs}
                m.setdefault('converted', m.get('admission', 'admission_done'))
                return m
        except Exception:  # noqa: BLE001
            pass
        return dict(DEFAULT_MAP)

    @api.constrains('name')
    def _check_name(self):
        for rec in self:
            if not (rec.name or '').strip():
                raise ValidationError(_('The label cannot be empty.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                base = _slug(vals.get('name'))
                code, n = base, 1
                while self.sudo().search_count([('code', '=', code)]):
                    n += 1
                    code = '%s_%s' % (base, n)
                vals['code'] = code
        return super().create(vals_list)

    def write(self, vals):
        if 'code' in vals and any(r.code != vals['code'] for r in self):
            raise UserError(_('The quality code cannot be changed.'))
        res = super().write(vals)
        if 'stage_id' in vals:
            self._recompute_leads_stage()
        return res

    def _recompute_leads_stage(self):
        leads = self.env['leads.logic'].sudo().with_context(active_test=False).search(
            [('lead_quality', 'in', self.mapped('code'))])
        if leads:
            leads._compute_lead_stage()

    def unlink(self):
        for rec in self:
            if rec.is_system:
                raise UserError(_('"%s" is a built-in quality and cannot be deleted.') % rec.name)
            if self.env['leads.logic'].sudo().with_context(active_test=False).search_count(
                    [('lead_quality', '=', rec.code)]):
                raise UserError(_('"%s" is used by leads. Move those leads to another quality first.') % rec.name)
        return super().unlink()
