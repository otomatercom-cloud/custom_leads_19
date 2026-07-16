from odoo import models, fields, api, _
from odoo.exceptions import UserError

# ---------------------------------------------------------------------------
# Priority order used for sorting leads within the daily queue.
# Leads are served Hot first, then Warm, Cold, Call Later, RNR, and the rest.
# ---------------------------------------------------------------------------
QUEUE_PRIORITY = [
    'hot', 'warm', 'cold', 'call_later', 'follow_up',
    'not_responding', 'not_reachable', 'not_attended', 'first_attempt', 'new',
    'waiting_for_admission', 'already_joined',
    'wrong_number', 'not_interested',
]


def _quality_priority(quality):
    try:
        return QUEUE_PRIORITY.index(quality)
    except ValueError:
        return len(QUEUE_PRIORITY)


# ---------------------------------------------------------------------------
# Mixin — added to leads.logic via _inherit
# ---------------------------------------------------------------------------
class LeadsLogicDailyQueueMixin(models.Model):
    """Adds daily queue fields and behaviour to leads.logic."""

    _inherit = 'leads.logic'

    # ── Daily Queue Fields ─────────────────────────────────────────────────
    daily_queue_date = fields.Date(
        string='Queue Date',
        help='The date on which this lead was placed in the officer daily queue.',
        index=True,
        copy=False,
    )
    daily_call_done = fields.Boolean(
        string='Called Today',
        default=False,
        copy=False,
        help='Marks that the officer has completed a call on this lead today.',
    )
    daily_call_sequence = fields.Integer(
        string='Queue Sequence',
        default=0,
        copy=False,
        help='Controls the order of leads within the same quality group in the daily queue.',
    )
    daily_call_time = fields.Datetime(
        string='Called At',
        readonly=True,
        copy=False,
        help='Timestamp of when the officer called this lead today.',
    )
    daily_call_count = fields.Integer(
        string="Today's Call Count",
        default=0,
        copy=False,
        help='Number of times this lead was called today.',
    )
    daily_queue_priority = fields.Integer(
        string='Queue Priority',
        compute='_compute_daily_queue_priority',
        store=True,
        help='Computed integer priority (lower = called first). Based on lead_quality.',
    )

    @api.depends('lead_quality')
    def _compute_daily_queue_priority(self):
        for rec in self:
            rec.daily_queue_priority = _quality_priority(rec.lead_quality or '')

    # ── Core Queue Action: mark called and rotate to end ──────────────────
    def action_mark_called_rotate(self):
        """
        Called when the officer finishes a call from the Kanban queue card.
        - Marks lead as called today.
        - Rotates the lead to the end of its quality group so the next
          uncalled lead surfaces at the top of the column.
        - Logs a call entry.
        """
        self.ensure_one()
        today = fields.Date.today()

        # Find the highest sequence in the same quality group for this officer today
        same_group = self.search([
            ('lead_owner', '=', self.lead_owner.id),
            ('lead_quality', '=', self.lead_quality),
            ('daily_queue_date', '=', today),
            ('id', '!=', self.id),
        ])
        max_seq = max(same_group.mapped('daily_call_sequence') or [0])

        self.write({
            'daily_call_done': True,
            'daily_call_time': fields.Datetime.now(),
            'daily_call_sequence': max_seq + 1,
            'daily_call_count': self.daily_call_count + 1,
        })

        # Log the call
        self.env['lead.call.log'].create({
            'lead_id': self.id,
            'user_id': self.env.user.id,
            'call_time': fields.Datetime.now(),
            'call_type': 'outgoing',
            'remarks': 'Daily queue call — marked done and rotated.',
        })
        self.message_post(
            body=_(
                '📞 <b>Daily queue call</b> completed by %(user)s. '
                'Lead rotated to end of queue.',
                user=self.env.user.name,
            )
        )
        return True

    # ── Skip: keep uncalled, move to end of quality group ─────────────────
    def action_queue_skip(self):
        """Move this lead to the end of its quality group without marking as called."""
        self.ensure_one()
        today = fields.Date.today()
        same_group = self.search([
            ('lead_owner', '=', self.lead_owner.id),
            ('lead_quality', '=', self.lead_quality),
            ('daily_queue_date', '=', today),
            ('id', '!=', self.id),
        ])
        max_seq = max(same_group.mapped('daily_call_sequence') or [0])
        self.write({'daily_call_sequence': max_seq + 1})
        self.message_post(body=_('⏭️ Lead skipped in daily queue by %(user)s.', user=self.env.user.name))
        return True

    # ── Open today's queue for the current officer in Kanban ──────────────
    def action_open_my_daily_queue(self):
        today = fields.Date.today()
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1
        )
        domain = [('daily_queue_date', '=', today)]
        if employee:
            domain.append(('lead_owner', '=', employee.id))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Today's Queue"),
            'res_model': 'leads.logic',
            'view_mode': 'kanban,list',
            'domain': domain,
            'context': {
                'search_default_uncalled_first': 1,
            },
        }

    # ── Dashboard summary data (called by JS dashboard widget) ────────────
    @api.model
    def get_today_queue_summary(self):
        """
        Returns a dict with today's queue stats for the current officer.
        Used by the dashboard "Today's Queue" card.
        """
        today = fields.Date.today()
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1
        )
        domain = [('daily_queue_date', '=', today)]
        if employee:
            domain.append(('lead_owner', '=', employee.id))

        leads = self.search(domain)
        by_quality = {}
        for lead in leads:
            q = lead.lead_quality or 'new'
            by_quality[q] = by_quality.get(q, 0) + 1

        called = leads.filtered('daily_call_done')
        return {
            'total': len(leads),
            'called': len(called),
            'remaining': len(leads) - len(called),
            'by_quality': by_quality,
            'officer': employee.name if employee else self.env.user.name,
        }

    @api.model
    def get_queue_dashboard_data(self):
        """
        Returns queue assignment and completion stats for Team Lead / Manager dashboard.
        Shows all officers with their assigned / completed / remaining counts for today.
        """
        today = fields.Date.today()
        all_queued = self.search([('daily_queue_date', '=', today)])

        # Group by officer
        officers = {}
        for lead in all_queued:
            owner = lead.lead_owner
            if not owner:
                continue
            key = owner.id
            if key not in officers:
                officers[key] = {
                    'name': owner.name,
                    'assigned': 0,
                    'completed': 0,
                    'remaining': 0,
                    'by_quality': {},
                }
            officers[key]['assigned'] += 1
            if lead.daily_call_done:
                officers[key]['completed'] += 1
            else:
                officers[key]['remaining'] += 1
            q = lead.lead_quality or 'new'
            officers[key]['by_quality'][q] = officers[key]['by_quality'].get(q, 0) + 1

        total_assigned = sum(o['assigned'] for o in officers.values())
        total_completed = sum(o['completed'] for o in officers.values())
        total_remaining = total_assigned - total_completed

        # Completion % per officer (sorted by name)
        officer_list = sorted(officers.values(), key=lambda o: o['name'])
        for o in officer_list:
            o['pct'] = round(o['completed'] / o['assigned'] * 100) if o['assigned'] else 0

        return {
            'date': str(today),
            'total_assigned': total_assigned,
            'total_completed': total_completed,
            'total_remaining': total_remaining,
            'officers': officer_list,
        }


# ---------------------------------------------------------------------------
# Scheduled action model (called by cron)
# ---------------------------------------------------------------------------
class LeadDailyQueueScheduler(models.Model):
    """Handles the nightly/morning queue rebuild for all officers."""

    _inherit = 'leads.logic'

    @api.model
    def action_rebuild_daily_queues(self):
        """
        Scheduled action — runs each morning (e.g. 7:00 AM).

        For every active lead owner (admission officer):
          1. Resets yesterday's queue flags.
          2. Finds all active leads assigned to them.
          3. Sorts by quality priority, then by id (stable secondary sort).
          4. Assigns daily_queue_date = today, daily_call_done = False,
             and incremental daily_call_sequence per quality group.

        Excludes leads already admitted or in junk stages.
        """
        today = fields.Date.today()

        EXCLUDED_QUALITIES = {
            'admission', 'already_joined',
            'wrong_number',
        }

        # Get all active lead owners
        officers = self.env['hr.employee'].search([
            ('user_id', '!=', False),
        ])

        for officer in officers:
            # Reset previous queue (yesterday's entries)
            prev_queue = self.search([
                ('lead_owner', '=', officer.id),
                ('daily_queue_date', '<', today),
                ('daily_queue_date', '!=', False),
            ])
            if prev_queue:
                prev_queue.write({
                    'daily_queue_date': False,
                    'daily_call_done': False,
                    'daily_call_sequence': 0,
                    'daily_call_count': 0,
                    'daily_call_time': False,
                })

            # Find today's active leads for this officer
            active_leads = self.search([
                ('lead_owner', '=', officer.id),
                ('lead_quality', 'not in', list(EXCLUDED_QUALITIES)),
                ('admission_status', '=', False),
            ])

            if not active_leads:
                continue

            # Sort: primary = quality priority, secondary = id (oldest first)
            sorted_leads = sorted(
                active_leads,
                key=lambda l: (_quality_priority(l.lead_quality or ''), l.id)
            )

            # Assign sequences per quality group
            quality_counters = {}
            for lead in sorted_leads:
                q = lead.lead_quality or 'new'
                seq = quality_counters.get(q, 0)
                lead.write({
                    'daily_queue_date': today,
                    'daily_call_done': False,
                    'daily_call_sequence': seq,
                    'daily_call_count': 0,
                    'daily_call_time': False,
                })
                quality_counters[q] = seq + 1
