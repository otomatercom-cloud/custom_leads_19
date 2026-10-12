# -*- coding: utf-8 -*-
"""Officer coaching: team leads listen to a recorded call and score it against a short checklist."""
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

SCORE = {'yes': 1.0, 'partial': 0.5, 'no': 0.0}


class LeadCoachingItem(models.Model):
    _name = 'lead.coaching.item'
    _description = 'Call coaching checklist item'
    _order = 'sequence, id'

    name = fields.Char(string='Checklist item', required=True)
    description = fields.Char(string='What a good call does')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class LeadCoachingReview(models.Model):
    _name = 'lead.coaching.review'
    _description = 'Call coaching review'
    _order = 'review_date desc, id desc'

    call_id = fields.Many2one('lead.call.log', string='Call', required=True, ondelete='cascade',
                              index=True, domain=[('has_recording', '=', True)])
    lead_id = fields.Many2one(related='call_id.lead_id', store=True, string='Lead')
    agent_id = fields.Many2one(related='call_id.user_id', store=True, string='Admission officer')
    call_time = fields.Datetime(related='call_id.call_time', string='Call time')
    call_duration = fields.Char(related='call_id.duration', string='Call length')
    reviewer_id = fields.Many2one('res.users', string='Reviewed by', default=lambda s: s.env.user,
                                  readonly=True, copy=False)
    review_date = fields.Datetime(default=fields.Datetime.now, readonly=True, copy=False)
    state = fields.Selection([('draft', 'In progress'), ('done', 'Done')], default='draft', index=True)
    line_ids = fields.One2many('lead.coaching.review.line', 'review_id', string='Checklist', copy=True)
    score = fields.Float(string='Score %', compute='_compute_score', store=True)
    result = fields.Selection([('good', 'Good'), ('help', 'Needs help')], compute='_compute_score', store=True)
    comments = fields.Text(string='Feedback for the officer')
    recording_player = fields.Html(compute='_compute_player', sanitize=False)

    _call_unique = models.Constraint('UNIQUE(call_id)', 'This call already has a review. Open it instead.')

    @api.depends('line_ids.answer')
    def _compute_score(self):
        pass_score = self.env['otm.lead.rule.params'].param('custom_leads_19.coaching_pass_score')
        for r in self:
            rated = r.line_ids.filtered(lambda l: l.answer in SCORE)
            r.score = round(sum(SCORE[l.answer] for l in rated) * 100.0 / len(rated), 1) if rated else 0.0
            r.result = ('good' if r.score >= pass_score else 'help') if rated else False

    @api.depends('call_id.recording_url', 'call_id.has_recording')
    def _compute_player(self):
        for r in self:
            c = r.call_id
            if c and c.recording_url:
                src = escape(c.recording_url)
            elif c and c.has_recording:
                src = Markup('/web/content/lead.call.log/%s/recording') % c.id
            else:
                r.recording_player = Markup('<em>No recording on this call.</em>')
                continue
            r.recording_player = Markup('<audio controls preload="none" style="width:100%%" src="%s"></audio>') % src

    @api.model_create_multi
    def create(self, vals_list):
        items = self.env['lead.coaching.item'].search([])
        for vals in vals_list:
            if not vals.get('line_ids'):
                vals['line_ids'] = [(0, 0, {'item_id': i.id}) for i in items]
        return super().create(vals_list)

    def action_done(self):
        for r in self:
            if any(l.answer == 'unrated' for l in r.line_ids):
                raise UserError(_('Rate every checklist item (or mark it Not applicable) before finishing.'))
        self.write({'state': 'done', 'reviewer_id': self.env.uid, 'review_date': fields.Datetime.now()})

    def action_reopen(self):
        self.write({'state': 'draft'})


class LeadCoachingReviewLine(models.Model):
    _name = 'lead.coaching.review.line'
    _description = 'Call coaching review line'
    _order = 'sequence, id'

    review_id = fields.Many2one('lead.coaching.review', required=True, ondelete='cascade', index=True)
    agent_id = fields.Many2one(related='review_id.agent_id', store=True)
    item_id = fields.Many2one('lead.coaching.item', string='Checklist item', required=True, ondelete='restrict')
    sequence = fields.Integer(related='item_id.sequence', store=True)
    hint = fields.Char(related='item_id.description', string='What a good call does')
    answer = fields.Selection([
        ('unrated', 'Not rated'), ('yes', 'Yes'), ('partial', 'Partly'), ('no', 'No'), ('na', 'Not applicable'),
    ], default='unrated', required=True)
    note = fields.Char(string='Note')


class LeadCallLogCoaching(models.Model):
    _inherit = 'lead.call.log'

    coaching_review_ids = fields.One2many('lead.coaching.review', 'call_id', string='Coaching reviews')

    def action_coach_review(self):
        """Open the coaching review of this call (created on first click)."""
        self.ensure_one()
        if not self.has_recording:
            raise UserError(_('This call has no recording to review.'))
        review = self.coaching_review_ids[:1] or self.env['lead.coaching.review'].create({'call_id': self.id})
        return {'type': 'ir.actions.act_window', 'res_model': 'lead.coaching.review',
                'res_id': review.id, 'view_mode': 'form', 'target': 'current'}
