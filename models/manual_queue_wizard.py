from odoo import models, fields, api, _
from odoo.exceptions import UserError

QUEUE_PRIORITY = [
    'hot', 'warm', 'cold', 'call_later', 'follow_up',
    'not_responding', 'not_reachable', 'not_attended', 'first_attempt', 'new',
    'waiting_for_admission', 'already_joined',
    'wrong_number', 'not_interested',
]

EXCLUDED_QUALITIES = {
    'admission', 'already_joined',
    'wrong_number',
}


def _quality_priority(quality):
    try:
        return QUEUE_PRIORITY.index(quality)
    except ValueError:
        return len(QUEUE_PRIORITY)


# ---------------------------------------------------------------------------
# Line model — each lead selected for the queue
# ---------------------------------------------------------------------------
class ManualQueueLine(models.TransientModel):
    _name = 'manual.queue.assign.line'
    _description = 'Manual Queue Assignment Line'
    _order = 'queue_priority asc, id asc'

    wizard_id = fields.Many2one('manual.queue.assign.wizard', ondelete='cascade')
    lead_id = fields.Many2one('leads.logic', string='Lead', required=True, readonly=True)
    lead_name = fields.Char(related='lead_id.name', readonly=True)
    phone_number = fields.Char(related='lead_id.phone_number', readonly=True)
    lead_quality = fields.Selection(related='lead_id.lead_quality', readonly=True)
    next_follow_up_date = fields.Date(related='lead_id.next_follow_up_date', readonly=True)
    selected = fields.Boolean(string='Include', default=True)
    queue_priority = fields.Integer(string='Priority', compute='_compute_priority', store=True)

    @api.depends('lead_quality')
    def _compute_priority(self):
        for rec in self:
            rec.queue_priority = _quality_priority(rec.lead_quality or '')


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------
class ManualQueueAssignWizard(models.TransientModel):
    _name = 'manual.queue.assign.wizard'
    _description = 'Manual Daily Queue Assignment'

    # ── Step 1: pick officer ───────────────────────────────────────────────
    officer_id = fields.Many2one(
        'hr.employee',
        string='Admission Officer',
        required=True,
        domain="[('user_id', '!=', False)]",
        help='Select the admission officer to assign the queue to.',
    )
    officer_user_id = fields.Many2one(
        'res.users',
        related='officer_id.user_id',
        readonly=True,
    )
    queue_date = fields.Date(
        string='Queue Date',
        default=fields.Date.today,
        required=True,
    )

    # ── Filters for loading leads ──────────────────────────────────────────
    filter_quality = fields.Selection([
        ('all', 'All Qualities'),
        ('hot', '🔥 Hot only'),
        ('warm', '🌞 Warm only'),
        ('cold', '❄️ Cold only'),
        ('not_responding', '🔕 RNR only'),
        ('hot_warm', '🔥 Hot + Warm'),
        ('hot_warm_cold', '🔥 Hot + Warm + Cold'),
        ('new', '🆕 New only'),
        ('first_attempt', '🎯 First Attempt only'),
        ('call_later', '📞 Call Back only'),
        ('follow_up', '⏰ Follow Up only'),
        ('not_reachable', '⏳ Busy only'),
        ('not_attended', '📵 Not Attended only'),
        ('waiting_for_admission', '⏳ Waiting for Admission only'),
    ], string='Filter by Quality', default='all')

    replace_existing = fields.Boolean(
        string='Replace existing queue',
        default=True,
        help='If checked, clears the officer\'s current queue for this date before assigning.',
    )

    # ── Step 2: lead lines ─────────────────────────────────────────────────
    line_ids = fields.One2many(
        'manual.queue.assign.line',
        'wizard_id',
        string='Leads',
    )

    total_leads = fields.Integer(compute='_compute_totals')
    selected_count = fields.Integer(compute='_compute_totals')
    hot_count = fields.Integer(compute='_compute_totals')
    warm_count = fields.Integer(compute='_compute_totals')
    cold_count = fields.Integer(compute='_compute_totals')
    rnr_count = fields.Integer(compute='_compute_totals')
    other_count = fields.Integer(compute='_compute_totals')

    @api.depends('line_ids', 'line_ids.selected', 'line_ids.lead_quality')
    def _compute_totals(self):
        for wiz in self:
            lines = wiz.line_ids
            selected = lines.filtered('selected')
            wiz.total_leads = len(lines)
            wiz.selected_count = len(selected)
            wiz.hot_count = len(selected.filtered(lambda l: l.lead_quality == 'hot'))
            wiz.warm_count = len(selected.filtered(lambda l: l.lead_quality == 'warm'))
            wiz.cold_count = len(selected.filtered(lambda l: l.lead_quality == 'cold'))
            wiz.rnr_count = len(selected.filtered(
                lambda l: l.lead_quality in ('not_responding', 'not_reachable')))
            wiz.other_count = len(selected.filtered(
                lambda l: l.lead_quality not in (
                    'hot', 'warm', 'cold', 'not_responding', 'not_reachable')))

    # ── Load leads button ──────────────────────────────────────────────────
    def action_load_leads(self):
        self.ensure_one()
        if not self.officer_id:
            raise UserError(_('Please select an admission officer first.'))

        domain = [
            ('lead_owner', '=', self.officer_id.id),
            ('lead_quality', 'not in', list(EXCLUDED_QUALITIES)),
            ('admission_status', '=', False),
        ]

        # Apply quality filter
        quality_map = {
            'hot': ['hot'],
            'warm': ['warm'],
            'cold': ['cold'],
            'not_responding': ['not_responding', 'not_reachable'],
            'hot_warm': ['hot', 'warm'],
            'hot_warm_cold': ['hot', 'warm', 'cold'],
            'new': ['new'],
            'first_attempt': ['first_attempt'],
            'call_later': ['call_later'],
            'follow_up': ['follow_up'],
            'not_reachable': ['not_reachable'],
            'not_attended': ['not_attended'],
            'waiting_for_admission': ['waiting_for_admission'],
        }
        if self.filter_quality and self.filter_quality != 'all':
            domain.append(('lead_quality', 'in', quality_map[self.filter_quality]))

        leads = self.env['leads.logic'].search(domain)

        # Sort by quality priority then id
        sorted_leads = sorted(leads, key=lambda l: (_quality_priority(l.lead_quality or ''), l.id))

        # Clear existing lines and rebuild
        self.line_ids = [(5, 0, 0)]
        lines = [(0, 0, {
            'lead_id': lead.id,
            'selected': True,
        }) for lead in sorted_leads]
        self.line_ids = lines

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'manual.queue.assign.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_select_all(self):
        self.line_ids.write({'selected': True})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'manual.queue.assign.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_deselect_all(self):
        self.line_ids.write({'selected': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'manual.queue.assign.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ── Assign queue ───────────────────────────────────────────────────────
    def action_assign_queue(self):
        self.ensure_one()
        selected_lines = self.line_ids.filtered('selected')
        if not selected_lines:
            raise UserError(_('Please select at least one lead to add to the queue.'))

        today = self.queue_date or fields.Date.today()

        # Clear existing queue for this officer on this date if replace is checked
        if self.replace_existing:
            existing = self.env['leads.logic'].search([
                ('lead_owner', '=', self.officer_id.id),
                ('daily_queue_date', '=', today),
            ])
            if existing:
                existing.write({
                    'daily_queue_date': False,
                    'daily_call_done': False,
                    'daily_call_sequence': 0,
                    'daily_call_count': 0,
                    'daily_call_time': False,
                })

        # Assign queue sequence per quality group
        quality_counters = {}
        for line in selected_lines.sorted(key=lambda l: (l.queue_priority, l.id)):
            q = line.lead_id.lead_quality or 'new'
            seq = quality_counters.get(q, 0)
            line.lead_id.write({
                'daily_queue_date': today,
                'daily_call_done': False,
                'daily_call_sequence': seq,
                'daily_call_count': 0,
                'daily_call_time': False,
            })
            line.lead_id.message_post(
                body=_(
                    '📋 <b>Added to daily queue</b> for %(officer)s on %(date)s '
                    'by %(user)s.',
                    officer=self.officer_id.name,
                    date=str(today),
                    user=self.env.user.name,
                )
            )
            quality_counters[q] = seq + 1

        # Notify the officer via inbox
        if self.officer_id.user_id and self.officer_id.user_id.partner_id:
            self.env['mail.message'].create({
                'message_type': 'notification',
                'body': _(
                    '📋 Your daily queue for <b>%(date)s</b> has been assigned by '
                    '<b>%(user)s</b>. <b>%(count)s leads</b> are ready. '
                    'Go to <b>My Queue Today</b> to start calling.',
                    date=str(today),
                    user=self.env.user.name,
                    count=len(selected_lines),
                ),
                'subject': _('Daily Queue Assigned'),
                'model': 'leads.logic',
                'res_id': selected_lines[0].lead_id.id,
                'partner_ids': [(4, self.officer_id.user_id.partner_id.id)],
                'author_id': self.env.user.partner_id.id,
                'notification_ids': [(0, 0, {
                    'res_partner_id': self.officer_id.user_id.partner_id.id,
                    'notification_type': 'inbox',
                })],
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Queue Assigned'),
                'message': _(
                    '%(count)s leads added to %(officer)s\'s queue for %(date)s.',
                    count=len(selected_lines),
                    officer=self.officer_id.name,
                    date=str(today),
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
