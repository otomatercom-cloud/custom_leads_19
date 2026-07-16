from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date, timedelta

QUALITY_PRIORITY = [
    'hot', 'warm', 'follow_up', 'call_later',
    'first_attempt', 'new', 'not_responding', 'cold',
    'waiting_for_admission', 'not_attended',
]
EXCLUDED_STATES = ['lost', 'qualified']
QUALITY_LABELS = {
    'new': '🆕 New', 'first_attempt': '🎯 First Attempt',
    'hot': '🔥 Hot', 'warm': '🌞 Warm', 'cold': '❄️ Cold',
    'follow_up': '⏰ Follow Up', 'call_later': '📞 Call Back',
    'not_responding': '🔕 Ringing Not Responding',
    'not_reachable': '⏳ Busy', 'waiting_for_admission': '⏳ Waiting for Admission',
    'wrong_number': '📵 Wrong number', 'not_interested': '❌ Not Interested',
    'not_attended': '📵Not Attended',
    'already_joined': '✅ Already Joined',
}


def _rank(lead, priority=QUALITY_PRIORITY):
    try:
        return priority.index(lead.lead_quality)
    except ValueError:
        return 99


class CallCampaignAutoGenerate(models.Model):
    """
    Campaign generation logic — called by dashboard JS and cron.
    Single method: generate_smart_campaigns(options)
    """
    _inherit = 'call.campaign'

    # ── Get selectable members for JS modal ─────────────────────────────
    @api.model
    def get_selectable_members(self):
        """
        Returns list of employees the current user can select for campaign generation.
        - Super admin / Manager: all team members + all TLs
        - Team Lead: their own team members (+ themselves)
        - Officer: just themselves
        """
        user = self.env.user
        is_manager = user.has_group('custom_leads_19.group_lead_manager')
        is_super   = user.has_group('custom_leads_19.group_super_admin')
        is_tl      = user.has_group('custom_leads_19.group_lead_team_lead')
        current_emp = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)

        employees = self.env['hr.employee']

        # Source of truth for "who is a team lead" is lead.team.team_lead_ids,
        # not the per-member "Reporting Team Lead" field on lead.team.member
        # (that field is optional and can be left blank on member lines, which
        # would silently hide a TL who has no members explicitly pointing to them).
        if is_manager or is_super:
            # All officers + all TLs, across every team
            all_teams = self.env['lead.team'].search([])
            employees = all_teams.mapped('member_ids.employee_id')
            tl_emps = all_teams.mapped('team_lead_ids')
            employees = (employees | tl_emps)
            # Fallback: anyone who owns leads
            if not employees:
                owner_ids = self.env['leads.logic'].search(
                    [('lead_owner', '!=', False)]
                ).mapped('lead_owner').ids
                employees = self.env['hr.employee'].browse(owner_ids)
        elif is_tl and current_emp:
            my_teams = self.env['lead.team'].search([('team_lead_ids', 'in', current_emp.id)])
            tl_emps = my_teams.mapped('team_lead_ids')
            employees = my_teams.mapped('member_ids.employee_id') | current_emp
        elif current_emp:
            tl_emps = self.env['hr.employee']
            employees = current_emp
        else:
            tl_emps = self.env['hr.employee']

        result = []
        for emp in employees:
            # Count active leads for this employee
            lead_count = self.env['leads.logic'].search_count([
                ('lead_owner', '=', emp.id),
                ('state', 'not in', ['lost', 'qualified']),
            ])
            is_emp_tl = emp in tl_emps
            result.append({
                'id': emp.id,
                'name': emp.name,
                'is_tl': is_emp_tl,
                'lead_count': lead_count,
                'job_title': emp.job_title or emp.job_id.name if emp.job_id else '',
            })

        # Sort: TLs first, then by name
        result.sort(key=lambda e: (0 if e['is_tl'] else 1, e['name']))
        return result

    # ── Get selectable lead sources for JS modal ─────────────────────────
    @api.model
    def get_selectable_sources(self):
        """Returns all leads.sources for the 'Select Source' chips.
        Empty selection in the modal means 'no source filter' (all sources)."""
        sources = self.env['leads.sources'].search([], order='name asc')
        return [{'id': s.id, 'name': s.name} for s in sources]

    # ── Core generate method ─────────────────────────────────────────────
    @api.model
    def generate_smart_campaigns(self, options=None):
        """
        options = {
            'campaign_type': 'combined' | 'all_leads' | 'quality' | 'date',
            'quality_filter': ['hot','warm',...],   # empty = all QUALITY_PRIORITY
            'date_from': 'YYYY-MM-DD',              # for 'date' type
            'date_to':   'YYYY-MM-DD',
            'max_leads':  50,
            'include_tl': True,
            'clear_existing': True,   # delete today's non-done campaigns first
            'auto_start': True,
        }
        Returns summary dict.
        """
        if options is None:
            options = {}

        user = self.env.user
        today = date.today()
        today_str = today.strftime('%d-%b-%Y')
        today_start = str(today) + ' 00:00:00'

        camp_type     = options.get('campaign_type', 'combined')
        quality_filter = options.get('quality_filter') or QUALITY_PRIORITY
        source_ids     = options.get('source_ids') or []   # empty = all sources
        max_leads      = int(options.get('max_leads', 50))
        include_tl     = options.get('include_tl', True)
        clear_existing = options.get('clear_existing', True)
        auto_start     = options.get('auto_start', True)
        date_from      = options.get('date_from', str(today))
        date_to        = options.get('date_to', str(today))

        # ── Determine who gets campaigns ─────────────────────────────────
        selected_ids = options.get('selected_employee_ids') or []
        is_manager = user.has_group('custom_leads_19.group_lead_manager')
        is_super   = user.has_group('custom_leads_19.group_super_admin')
        is_tl      = user.has_group('custom_leads_19.group_lead_team_lead')
        current_emp = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)

        # Source of truth for "who is a team lead" is lead.team.team_lead_ids
        # (see get_selectable_members for why the per-member field isn't used).
        all_tl_emps = self.env['lead.team'].search([]).mapped('team_lead_ids')

        if selected_ids:
            # Use explicitly selected employees (validated by get_selectable_members scope)
            employees = self.env['hr.employee'].browse(selected_ids)
        elif is_manager or is_super:
            all_teams = self.env['lead.team'].search([])
            employees = all_teams.mapped('member_ids.employee_id')
            if include_tl:
                employees = employees | all_teams.mapped('team_lead_ids')
            if not employees:
                owner_ids = self.env['leads.logic'].search(
                    [('lead_owner', '!=', False)]
                ).mapped('lead_owner').ids
                employees = self.env['hr.employee'].browse(owner_ids)
        elif is_tl and current_emp:
            my_teams = self.env['lead.team'].search([('team_lead_ids', 'in', current_emp.id)])
            employees = my_teams.mapped('member_ids.employee_id')
            if include_tl:
                employees = employees | current_emp
        else:
            employees = current_emp

        if not employees:
            return {'created': 0, 'deleted': 0, 'skipped': 0, 'officers': [],
                    'error': 'No employees found.'}

        # ── Clear existing campaigns (today's non-done) ──────────────────
        deleted_count = 0
        if clear_existing:
            existing = self.search([('state', 'not in', ['done'])])
            deleted_count = len(existing)
            existing.unlink()

        # ── Generate per employee — split by quality group ──────────────
        created = 0
        skipped = 0
        officer_summary = []
        state = 'running' if auto_start else 'draft'

        for emp in employees:
            is_emp_tl = emp in all_tl_emps
            role_tag = ' (TL)' if is_emp_tl else ''

            # Get leads grouped by quality
            quality_groups = self._get_leads_grouped_by_quality(
                emp, camp_type, quality_filter, source_ids,
                today_start, date_from, date_to
            )

            emp_created = 0
            emp_total_leads = 0

            for q_value, q_label, leads in quality_groups:
                if not leads:
                    continue
                emp_total_leads += len(leads)

                # Split this quality group by batch size
                batch = max_leads or 50
                chunks = [leads[i:i + batch] for i in range(0, len(leads), batch)]

                for idx, chunk in enumerate(chunks, 1):
                    part = f' ({idx})' if len(chunks) > 1 else ''
                    camp_name = (
                        f"{emp.name}{role_tag} — {q_label}{part} — {today_str}"
                    )
                    existing = self.search([('name', '=', camp_name)], limit=1)
                    if existing and not clear_existing:
                        skipped += 1
                        continue
                    self.create({
                        'name': camp_name,
                        'state': state,
                        'lead_ids': [(6, 0, [l.id for l in chunk])],
                    })
                    created += 1
                    emp_created += 1

            if emp_created:
                officer_summary.append({
                    'name': emp.name + role_tag,
                    'leads': emp_total_leads,
                    'campaigns': emp_created,
                    'status': f'{emp_created} campaign(s) created',
                })

        return {
            'created': created,
            'deleted': deleted_count,
            'skipped': skipped,
            'total_employees': len(employees),
            'officers': officer_summary,
            'campaign_type': camp_type,
        }

    def _get_leads_grouped_by_quality(self, emp, camp_type, quality_filter, source_ids,
                                       today_start, date_from, date_to):
        """
        Return list of (quality_value, quality_label, [leads]) tuples.

        Leads are first collected based on campaign type, then grouped by
        lead_quality.  Within each group they are sorted by id (oldest first).
        Groups are ordered by QUALITY_PRIORITY rank.

        `source_ids`: list of leads.sources ids to restrict to. Empty list
        means no source filter (all sources included) — this keeps the cron
        (auto_create_all_officer_campaigns) and any old callers behaving
        exactly as before this filter was added.

        For 'combined': today's new leads AND older quality-matching leads are
        collected together, then grouped — so each quality campaign contains
        both today's fresh leads and older ones for that quality.
        """
        base = [
            ('lead_owner', '=', emp.id),
            ('state', 'not in', EXCLUDED_STATES),
        ]
        if source_ids:
            base.append(('leads_source', 'in', source_ids))

        if camp_type == 'combined':
            # Today's new leads (any quality)
            today_new = self.env['leads.logic'].search(
                base + [('create_date', '>=', today_start)], order='id asc'
            )
            # Older leads matching quality filter
            old_q = self.env['leads.logic'].search(
                base + [
                    ('create_date', '<', today_start),
                    ('lead_quality', 'in', quality_filter),
                ], order='id asc'
            )
            # Merge: today first, then old; deduplicate
            all_leads = list(today_new) + [l for l in old_q if l not in today_new]

        elif camp_type == 'all_leads':
            all_leads = list(self.env['leads.logic'].search(base, order='id asc'))

        elif camp_type == 'quality':
            all_leads = list(self.env['leads.logic'].search(
                base + [('lead_quality', 'in', quality_filter)], order='id asc'
            ))

        elif camp_type == 'date':
            date_domain = base[:]
            if date_from:
                date_domain.append(('create_date', '>=', date_from + ' 00:00:00'))
            if date_to:
                date_domain.append(('create_date', '<=', date_to + ' 23:59:59'))
            all_leads = list(self.env['leads.logic'].search(date_domain, order='id asc'))

        else:
            return []

        # Group by quality
        from collections import defaultdict
        groups = defaultdict(list)
        for lead in all_leads:
            q = lead.lead_quality or 'new'
            groups[q].append(lead)

        # Build ordered result list (QUALITY_PRIORITY order; unknowns at end)
        seen_qualities = set(groups.keys())
        ordered_qualities = [q for q in QUALITY_PRIORITY if q in seen_qualities]
        ordered_qualities += [q for q in seen_qualities if q not in QUALITY_PRIORITY]

        result = []
        for q in ordered_qualities:
            label = QUALITY_LABELS.get(q, q.replace('_', ' ').title())
            result.append((q, label, groups[q]))

        return result

    # ── Cron: auto daily ─────────────────────────────────────────────────
    @api.model
    def auto_create_all_officer_campaigns(self):
        """Cron at 8:00 AM — clears today's campaigns, rebuilds for everyone."""
        return self.generate_smart_campaigns({
            'campaign_type': 'combined',
            'quality_filter': QUALITY_PRIORITY,
            'max_leads': 50,
            'include_tl': True,
            'clear_existing': True,
            'auto_start': True,
        })


class LeadsLogicCampaign(models.Model):
    """Auto-add new leads to today's running campaign for the assigned officer/TL."""
    _inherit = 'leads.logic'

    campaign_call_done = fields.Boolean(string='Campaign Called', default=False)
    campaign_ids = fields.Many2many(
        'call.campaign', 'call_campaign_lead_rel', 'lead_id', 'campaign_id',
        string='Campaigns'
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        today = date.today()
        today_str = today.strftime('%d-%b-%Y')
        today_start = str(today) + ' 00:00:00'

        for lead in records:
            if not lead.lead_owner:
                continue
            # Find today's running campaign for this lead's owner
            campaign = self.env['call.campaign'].search([
                ('state', '=', 'running'),
                ('create_date', '>=', today_start),
                ('lead_ids', '!=', False),
            ], limit=0)  # search all, filter by owner below

            # Filter: campaigns that contain at least one lead owned by this employee
            emp = lead.lead_owner  # hr.employee
            for c in self.env['call.campaign'].search([
                ('state', '=', 'running'),
                ('create_date', '>=', today_start),
            ]):
                # Check if campaign belongs to this employee (lead_owner match)
                if c.lead_ids and c.lead_ids[0].lead_owner == emp:
                    c.write({'lead_ids': [(4, lead.id)]})
                    break
        return records
