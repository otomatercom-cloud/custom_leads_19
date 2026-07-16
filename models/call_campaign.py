from odoo import models, fields, api, _
from odoo.exceptions import UserError

QUALITY_SELECTION = [
    ('new', '🆕 New'),
    ('first_attempt', '🎯 First Attempt'),
    ('waiting_for_admission', '⏳ Waiting for Admission'),
    ('admission', '🎓 Admission'),
    ('hot', '🔥 Hot'),
    ('warm', '🌞 Warm'),
    ('cold', '❄️ Cold'),
    ('not_responding', '🔕 Ringing Not Responding'),
    ('call_later', '📞 Call Back'),
    ('follow_up', '⏰ Follow Up'),
    ('not_reachable', '⏳ Busy'),
    ('wrong_number', '📵 Wrong number'),
    ('not_interested', '❌ Not Interested'),
    ('not_attended', '📵Not Attended'),
    ('already_joined', '✅ Already Joined'),
]


class CallCampaign(models.Model):
    _name = 'call.campaign'
    _description = 'Call Campaign'
    _order = 'create_date desc'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Campaign Name', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('done', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    created_by = fields.Many2one('res.users', string='Created By',
                                  default=lambda self: self.env.user, readonly=True)
    description = fields.Text(string='Notes')

    # ── Filters ───────────────────────────────────────────────────────────
    filter_lead_quality = fields.Many2many(
        'call.campaign.quality', 'campaign_quality_rel', 'campaign_id', 'quality_id',
        string='Filter by Quality',
    )
    filter_lead_owner = fields.Many2many(
        'hr.employee', 'campaign_owner_rel', 'campaign_id', 'employee_id',
        string='Filter by Lead Owner'
    )
    filter_leads_source = fields.Many2many(
        'leads.sources', 'campaign_source_rel', 'campaign_id', 'source_id',
        string='Filter by Source'
    )
    filter_team = fields.Many2many(
        'lead.team', 'campaign_team_rel', 'campaign_id', 'team_id',
        string='Filter by Team'
    )

    # ── Leads ─────────────────────────────────────────────────────────────
    lead_ids = fields.Many2many(
        'leads.logic', 'call_campaign_lead_rel', 'campaign_id', 'lead_id',
        string='Leads'
    )
    lead_count = fields.Integer(string='Total Leads', compute='_compute_counts', store=True)
    called_count = fields.Integer(string='Called', compute='_compute_counts', store=True)
    pending_count = fields.Integer(string='Pending', compute='_compute_counts', store=True)

    @api.depends('lead_ids', 'lead_ids.campaign_call_done')
    def _compute_counts(self):
        for rec in self:
            rec.lead_count = len(rec.lead_ids)
            rec.called_count = len(rec.lead_ids.filtered('campaign_call_done'))
            rec.pending_count = rec.lead_count - rec.called_count
            # Auto-mark done when all leads are called
            if rec.lead_count > 0 and rec.called_count == rec.lead_count and rec.state == 'running':
                rec.state = 'done'

    # ── Actions ───────────────────────────────────────────────────────────
    def action_load_leads(self):
        domain = []
        if self.filter_lead_quality:
            domain.append(('lead_quality', 'in', self.filter_lead_quality.mapped('value')))
        if self.filter_lead_owner:
            domain.append(('lead_owner', 'in', self.filter_lead_owner.ids))
        if self.filter_leads_source:
            domain.append(('leads_source', 'in', self.filter_leads_source.ids))
        if self.filter_team:
            domain.append(('team_id', 'in', self.filter_team.ids))
        leads = self.env['leads.logic'].search(domain, limit=500)
        self.lead_ids = [(6, 0, leads.ids)]
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Leads Loaded',
                'message': f'{len(leads)} leads added to campaign.',
                'type': 'success',
            }
        }

    def action_start(self):
        if not self.lead_ids:
            raise UserError('Add leads to the campaign before starting.')
        self.state = 'running'
        return self.action_open_runner()

    def action_open_runner(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'call_campaign_runner',
            'name': f'📞 {self.name}',
            'params': {'campaign_id': self.id},
        }

    def action_mark_done(self):
        self.state = 'done'

    def action_cancel(self):
        self.state = 'cancelled'

    def action_reset(self):
        self.state = 'draft'
        self.lead_ids.write({'campaign_call_done': False})

    @api.model
    def action_start_all_drafts(self, campaign_ids=None):
        """Start all draft campaigns (or specific ones by id list)."""
        if campaign_ids:
            campaigns = self.browse(campaign_ids).filtered(lambda c: c.state == 'draft' and c.lead_ids)
        else:
            campaigns = self.search([('state', '=', 'draft'), ('lead_count', '>', 0)])
        campaigns.write({'state': 'running'})
        return {'started': len(campaigns), 'names': campaigns.mapped('name')}

    # ── RPC helpers for JS ────────────────────────────────────────────────
    @api.model
    def get_campaign_leads(self, campaign_id):
        campaign = self.browse(campaign_id)
        quality_map = dict(QUALITY_SELECTION)
        leads = []
        for lead in campaign.lead_ids:
            leads.append({
                'id': lead.id,
                'name': lead.name,
                'phone': lead.phone_number or '',
                'quality': lead.lead_quality or 'new',
                'quality_label': quality_map.get(lead.lead_quality, lead.lead_quality or ''),
                'call_response': lead.call_response or '',
                'called': lead.campaign_call_done,
                'reference': lead.reference_no or '',
                'course': ', '.join(lead.course_inter.mapped('name')) if lead.course_inter else '',
                'lead_owner': lead.lead_owner.name if lead.lead_owner else '',
            })
        called = len([l for l in leads if l['called']])
        return {
            'campaign_name': campaign.name,
            'total': len(leads),
            'called': called,
            'pending': len(leads) - called,
            'leads': leads,
            'quality_options': QUALITY_SELECTION,
        }

    @api.model
    def submit_call_response(self, campaign_id, lead_id, quality, response,
                             followup_date=False, followup_notes=""):
        """Save quality + response, mark lead as called, optionally schedule follow-up."""
        lead = self.env['leads.logic'].browse(lead_id)
        vals = {'campaign_call_done': True}
        if quality:
            vals['lead_quality'] = quality
        if response:
            vals['call_response'] = response
            # Also add to response_ids log
            self.env['lead.response'].create({
                'lead_id': lead_id,
                'comment': response,
                'user_id': self.env.uid,
            })
        lead.write(vals)

        # ── Chatter note ─────────────────────────────────────────────────
        quality_label = dict(QUALITY_SELECTION).get(quality, quality or '')
        msg = _('📞 <b>Campaign Call</b> — Quality: %s') % quality_label
        if response:
            msg += '<br/>' + response
        lead.message_post(body=msg, subtype_xmlid='mail.mt_note')

        # ── Schedule follow-up if requested ──────────────────────────────
        if followup_date and 'lead.followup' in self.env:
            from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
            # followup_date arrives as "YYYY-MM-DDTHH:MM" from datetime-local input
            followup_date_clean = followup_date.replace('T', ' ')
            if len(followup_date_clean) == 16:
                followup_date_clean += ':00'
            try:
                from datetime import datetime
                dt = datetime.strptime(followup_date_clean, '%Y-%m-%d %H:%M:%S')
            except Exception:
                dt = False
            if dt:
                self.env['lead.followup'].create({
                    'lead_id':            lead.id,
                    'next_followup_date': dt,
                    'remarks':            followup_notes or '',
                    'phone_number':       lead.phone_number or '',
                    'user_id':            self.env.user.id,
                    'status':             'scheduled',
                })
                fu_msg = _('📅 <b>Follow-Up Scheduled</b> for %s by %s%s') % (
                    dt.strftime('%d %b %Y %H:%M'),
                    self.env.user.name,
                    (' — ' + followup_notes) if followup_notes else '',
                )
                lead.message_post(body=fu_msg, subtype_xmlid='mail.mt_note')

        return True


    @api.model
    def get_or_create_daily_campaign(self):
        """
        Auto-creates/finds today's daily call campaign for the current user.
        Works even if no employee record is linked (falls back to all leads
        assigned to leads_owner whose user_id matches, or created_by user).
        Max 50 leads sorted by quality priority.
        """
        from datetime import date

        user = self.env.user
        today = date.today()
        today_str = today.strftime('%Y-%m-%d')

        # Try to find linked employee
        employee = self.env['hr.employee'].search(
            [('user_id', '=', user.id)], limit=1
        )

        user_label = employee.name if employee else user.name
        campaign_name = f"Daily Campaign - {user_label} - {today_str}"

        # Find existing today's campaign for this user
        existing = self.search([
            ('name', '=', campaign_name),
            ('created_by', '=', user.id),
        ], limit=1)

        if existing:
            campaign = existing
        else:
            quality_priority = [
                'hot', 'warm', 'follow_up', 'call_later',
                'first_attempt', 'new', 'not_responding', 'cold',
                'waiting_for_admission', 'not_attended',
            ]

            # Build domain based on whether employee exists
            if employee:
                domain = [
                    ('lead_owner', '=', employee.id),
                    ('state', 'not in', ['lost', 'qualified']),
                    ('lead_quality', 'in', quality_priority),
                ]
            else:
                # Fallback: leads created by this user
                domain = [
                    ('lead_creator_id', '=', user.id),
                    ('state', 'not in', ['lost', 'qualified']),
                    ('lead_quality', 'in', quality_priority),
                ]

            all_leads = self.env['leads.logic'].search(domain, order='id asc')

            def quality_rank(lead):
                try:
                    return quality_priority.index(lead.lead_quality)
                except ValueError:
                    return 99

            sorted_leads = sorted(all_leads, key=quality_rank)[:50]

            campaign = self.create({
                'name': campaign_name,
                'state': 'running',
                'lead_ids': [(6, 0, [l.id for l in sorted_leads])],
            })

        return {
            'campaign_id': campaign.id,
            'campaign_name': campaign.name,
            'state': campaign.state,
            'total': campaign.lead_count,
            'called': campaign.called_count,
            'pending': campaign.pending_count,
        }


    @api.model
    def _create_campaign_for_employee(self, employee, today_str, quality_priority):
        """Internal helper: create or return today's campaign for one employee."""
        campaign_name = f"Daily Campaign - {employee.name} - {today_str}"
        existing = self.search([
            ('name', '=', campaign_name),
        ], limit=1)
        if existing:
            return existing

        all_leads = self.env['leads.logic'].search([
            ('lead_owner', '=', employee.id),
            ('state', 'not in', ['lost', 'qualified']),
            ('lead_quality', 'in', quality_priority),
        ], order='id asc')

        def quality_rank(lead):
            try:
                return quality_priority.index(lead.lead_quality)
            except ValueError:
                return 99

        sorted_leads = sorted(all_leads, key=quality_rank)[:50]
        return self.create({
            'name': campaign_name,
            'state': 'running',
            'lead_ids': [(6, 0, [l.id for l in sorted_leads])],
        })

    @api.model
    def generate_team_campaigns(self, team_lead_employee_id=None):
        """
        Called by Team Lead button on dashboard.
        Creates daily campaigns for all officers under the TL's teams.
        If team_lead_employee_id is None → generates for ALL officers (manager use).
        Returns summary dict.
        """
        from datetime import date
        today_str = date.today().strftime('%Y-%m-%d')
        quality_priority = [
            'hot', 'warm', 'follow_up', 'call_later',
            'first_attempt', 'new', 'not_responding', 'cold',
            'waiting_for_admission', 'not_attended',
        ]

        if team_lead_employee_id:
            # Find officers under this TL
            tl_employee = self.env['hr.employee'].browse(team_lead_employee_id)
            members = self.env['lead.team.member'].search([
                ('team_lead_id', '=', tl_employee.id),
            ])
            officers = members.mapped('employee_id')
        else:
            # All officers (manager use)
            all_members = self.env['lead.team.member'].search([])
            officers = all_members.mapped('employee_id')

        created = 0
        existing = 0
        for officer in officers:
            campaign_name = f"Daily Campaign - {officer.name} - {today_str}"
            if self.search([('name', '=', campaign_name)], limit=1):
                existing += 1
            else:
                self._create_campaign_for_employee(officer, today_str, quality_priority)
                created += 1

        return {
            'created': created,
            'existing': existing,
            'total': len(officers),
        }

    @api.model
    def get_dashboard_campaign_info(self):
        """
        Returns info for the dashboard:
        - For officers: their own daily campaign
        - For TL/manager: list of their team officers + campaign status
        """
        from datetime import date
        user = self.env.user
        today_str = date.today().strftime('%Y-%m-%d')
        is_tl      = user.has_group('custom_leads_19.group_lead_team_lead')
        is_manager = user.has_group('custom_leads_19.group_lead_manager')
        is_super   = user.has_group('custom_leads_19.group_super_admin')

        employee = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)

        result = {
            'role': 'manager' if (is_manager or is_super) else ('tl' if is_tl else 'officer'),
            'employee_id': employee.id if employee else False,
            'own_campaign': None,
            'team_summary': None,
        }

        # Always include own campaign for the current user
        own = self.get_or_create_daily_campaign()
        if 'error' not in own:
            result['own_campaign'] = own

        # For TL/Manager: also show team campaign summary
        if is_tl or is_manager or is_super:
            if is_tl and employee:
                members = self.env['lead.team.member'].search([
                    ('team_lead_id', '=', employee.id),
                ])
                officers = members.mapped('employee_id')
            else:
                # Manager: all officers
                members = self.env['lead.team.member'].search([])
                officers = members.mapped('employee_id')

            team_campaigns = []
            for officer in officers:
                campaign_name = f"Daily Campaign - {officer.name} - {today_str}"
                campaign = self.search([('name', '=', campaign_name)], limit=1)
                team_campaigns.append({
                    'employee_name': officer.name,
                    'employee_id': officer.id,
                    'has_campaign': bool(campaign),
                    'campaign_id': campaign.id if campaign else False,
                    'total': campaign.lead_count if campaign else 0,
                    'called': campaign.called_count if campaign else 0,
                    'pending': campaign.pending_count if campaign else 0,
                })

            result['team_summary'] = {
                'officers': team_campaigns,
                'total_officers': len(officers),
                'campaigns_created': len([c for c in team_campaigns if c['has_campaign']]),
                'tl_employee_id': employee.id if employee else False,
            }

        return result


    @api.model
    def generate_campaigns(self, options=None):
        """
        Generate call campaigns by splitting each admission officer's active leads
        into batches of `batch_size` (default 25).

        options = {
            'batch_size': 25,
            'employee_ids': [...],   # optional: restrict to specific employees
        }

        Returns summary:
        {
            'created': int,
            'skipped': int,
            'officers': [{'name': ..., 'campaigns': int, 'leads': int, 'total_chunks': int}, ...]
        }
        """
        from datetime import date
        if options is None:
            options = {}

        batch_size = int(options.get('batch_size', 25))
        today_str = date.today().strftime('%Y-%m-%d')

        # Determine which employees to generate for
        if options.get('employee_ids'):
            employees = self.env['hr.employee'].browse(options['employee_ids'])
        else:
            user = self.env.user
            is_manager = user.has_group('custom_leads_19.group_lead_manager')
            is_super   = user.has_group('custom_leads_19.group_super_admin')
            is_tl      = user.has_group('custom_leads_19.group_lead_team_lead')
            current_emp = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)

            if is_manager or is_super:
                members = self.env['lead.team.member'].search([])
                employees = members.mapped('employee_id')
                if not employees:
                    lead_owner_ids = self.env['leads.logic'].search(
                        [('lead_owner', '!=', False)]
                    ).mapped('lead_owner').ids
                    employees = self.env['hr.employee'].browse(lead_owner_ids)
            elif is_tl and current_emp:
                members = self.env['lead.team.member'].search(
                    [('team_lead_id', '=', current_emp.id)]
                )
                employees = members.mapped('employee_id')
            else:
                employees = current_emp

        quality_priority = [
            'hot', 'warm', 'follow_up', 'call_later',
            'first_attempt', 'new', 'not_responding', 'cold',
            'waiting_for_admission', 'not_attended',
        ]
        excluded_states = ['lost', 'qualified']

        created_total = 0
        skipped_total = 0
        officer_summary = []

        for employee in employees:
            leads = self.env['leads.logic'].search([
                ('lead_owner', '=', employee.id),
                ('state', 'not in', excluded_states),
            ], order='id asc')

            if not leads:
                continue

            def quality_rank(lead):
                try:
                    return quality_priority.index(lead.lead_quality)
                except ValueError:
                    return 99

            sorted_leads = sorted(leads, key=quality_rank)
            chunks = [
                sorted_leads[i:i + batch_size]
                for i in range(0, len(sorted_leads), batch_size)
            ]

            emp_created = 0
            for idx, chunk in enumerate(chunks, start=1):
                campaign_name = f"{employee.name} - Campaign {idx} - {today_str}"
                existing = self.search([('name', '=', campaign_name)], limit=1)
                if existing:
                    skipped_total += 1
                    continue
                self.create({
                    'name': campaign_name,
                    'state': 'draft',
                    'lead_ids': [(6, 0, [l.id for l in chunk])],
                })
                emp_created += 1
                created_total += 1

            officer_summary.append({
                'name': employee.name,
                'campaigns': emp_created,
                'leads': len(sorted_leads),
                'total_chunks': len(chunks),
            })

        return {
            'created': created_total,
            'skipped': skipped_total,
            'officers': officer_summary,
            'batch_size': batch_size,
        }

    @api.model
    def get_campaign_dashboard_data(self):
        """Returns all campaigns visible to current user with stats + team breakdown."""
        user = self.env.user
        is_manager = user.has_group('custom_leads_19.group_lead_manager')
        is_super   = user.has_group('custom_leads_19.group_super_admin')
        is_tl      = user.has_group('custom_leads_19.group_lead_team_lead')
        employee   = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)

        role = 'manager' if (is_manager or is_super) else ('tl' if is_tl else 'officer')

        # Scope campaigns by role
        if is_manager or is_super:
            campaigns = self.search([], order='create_date desc')
        elif is_tl:
            if employee:
                # Source of truth for "which team(s) am I TL of" is lead.team.team_lead_ids
                # (a TL can lead a team even if some/all member lines have no team_lead_id set).
                my_teams = self.env['lead.team'].search([('team_lead_ids', 'in', employee.id)])
                members = my_teams.mapped('member_ids')
                officer_ids = members.mapped('employee_id.user_id').ids
                officer_emp_ids = members.mapped('employee_id').ids
                # Campaigns created by TL/officers OR containing their leads
                self.env.cr.execute(
                    """SELECT DISTINCT campaign_id FROM call_campaign_lead_rel
                       WHERE lead_id IN (
                           SELECT id FROM leads_logic WHERE lead_owner = ANY(%s)
                       )""", ([employee.id] + officer_emp_ids,)
                )
                lead_campaign_ids = [r[0] for r in self.env.cr.fetchall()]
                campaigns = self.search([
                    '|', ('created_by', 'in', [user.id] + officer_ids),
                    ('id', 'in', lead_campaign_ids)
                ], order='create_date desc')
            else:
                campaigns = self.search([('created_by', '=', user.id)], order='create_date desc')
        else:
            # Officer: campaigns created by them OR campaigns containing their leads
            if employee:
                # Query via relation table
                self.env.cr.execute(
                    """SELECT DISTINCT campaign_id FROM call_campaign_lead_rel
                       WHERE lead_id IN (
                           SELECT id FROM leads_logic WHERE lead_owner = %s
                       )""", (employee.id,)
                )
                lead_campaign_ids = [r[0] for r in self.env.cr.fetchall()]
                campaigns = self.search([
                    '|', ('created_by', '=', user.id),
                    ('id', 'in', lead_campaign_ids)
                ], order='create_date desc')
            else:
                campaigns = self.search([('created_by', '=', user.id)], order='create_date desc')

        # Get all campaign IDs that belong to current employee's leads (for is_mine)
        my_campaign_ids = set()
        if employee:
            self.env.cr.execute(
                """SELECT DISTINCT campaign_id FROM call_campaign_lead_rel
                   WHERE lead_id IN (SELECT id FROM leads_logic WHERE lead_owner = %s)""",
                (employee.id,)
            )
            my_campaign_ids = {r[0] for r in self.env.cr.fetchall()}

        result = []
        for c in campaigns:
            if c.lead_count == 0:
                continue  # skip empty campaigns from dashboard
            result.append({
                'id': c.id,
                'name': c.name,
                'state': c.state,
                'created_by': c.created_by.name if c.created_by else '',
                'created_by_id': c.created_by.id if c.created_by else False,
                'date': str(c.create_date.date()) if c.create_date else '',
                'total': c.lead_count,
                'called': c.called_count,
                'pending': c.pending_count,
                'is_mine': c.created_by.id == user.id or c.id in my_campaign_ids,
            })

        running = [c for c in result if c['state'] == 'running']
        draft   = [c for c in result if c['state'] == 'draft']
        done    = [c for c in result if c['state'] == 'done' or (c['total'] > 0 and c['called'] == c['total'])]

        # ── Team/Officer breakdown for TL and Manager ─────────────────────
        officer_breakdown = []
        if is_manager or is_super or is_tl:
            if is_tl and employee:
                my_teams = self.env['lead.team'].search([('team_lead_ids', 'in', employee.id)])
                officers = my_teams.mapped('member_ids.employee_id') | employee  # TL(s) + their team
                tl_emps  = my_teams.mapped('team_lead_ids')
            else:
                all_teams = self.env['lead.team'].search([])
                officers  = all_teams.mapped('member_ids.employee_id')
                # Also include ALL team leads — sourced from lead.team.team_lead_ids,
                # not from the per-member "Reporting Team Lead" field (which can be
                # left blank on member lines and would silently hide a TL with no
                # assigned members, e.g. a second/newer TL).
                tl_emps   = all_teams.mapped('team_lead_ids')
                officers  = officers | tl_emps

            if officers:
                # One SQL: for each employee → which campaign IDs contain their leads
                emp_ids = list(officers.ids)
                self.env.cr.execute("""
                    SELECT ll.lead_owner, ccr.campaign_id
                      FROM call_campaign_lead_rel ccr
                      JOIN leads_logic ll ON ll.id = ccr.lead_id
                     WHERE ll.lead_owner = ANY(%s)
                """, (emp_ids,))
                from collections import defaultdict
                emp_campaign_map = defaultdict(set)
                for emp_id, camp_id in self.env.cr.fetchall():
                    emp_campaign_map[emp_id].add(camp_id)

                # Index result by campaign id for fast lookup
                result_by_id = {c['id']: c for c in result}

                for officer in officers:
                    eid  = officer.id
                    cids = emp_campaign_map.get(eid, set())
                    # Only campaigns visible in current result set
                    officer_campaigns = [result_by_id[cid] for cid in cids if cid in result_by_id]

                    total_leads   = sum(c['total']   for c in officer_campaigns)
                    total_called  = sum(c['called']  for c in officer_campaigns)
                    total_pending = sum(c['pending'] for c in officer_campaigns)
                    completed_c   = len([c for c in officer_campaigns
                                         if c['state'] == 'done'
                                         or (c['total'] > 0 and c['called'] == c['total'])])
                    running_c     = len([c for c in officer_campaigns if c['state'] == 'running'])
                    draft_c       = len([c for c in officer_campaigns if c['state'] == 'draft'])
                    pct = round((total_called / total_leads * 100)) if total_leads else 0

                    # Check if this employee is a TL
                    is_emp_tl = officer in tl_emps

                    officer_breakdown.append({
                        'employee_name': officer.name + (' (TL)' if is_emp_tl else ''),
                        'employee_id':   eid,
                        'is_tl':         is_emp_tl,
                        'total_campaigns': len(officer_campaigns),
                        'completed':     completed_c,
                        'running':       running_c,
                        'draft':         draft_c,
                        'total_leads':   total_leads,
                        'called':        total_called,
                        'pending':       total_pending,
                        'pct':           pct,
                    })

            # Sort: TLs first, then by pct desc
            officer_breakdown.sort(key=lambda o: (0 if o.get('is_tl') else 1, -o['pct']))

        return {
            'role': role,
            'campaigns': result,
            'officer_breakdown': officer_breakdown,
            'stats': {
                'total': len(result),
                'running': len(running),
                'draft': len(draft),
                'done': len(done),
                'total_leads': sum(c['total'] for c in result),
                'total_called': sum(c['called'] for c in result),
                'total_pending': sum(c['pending'] for c in result),
            },
        }


class CallCampaignQuality(models.Model):
    """Helper model so quality filter can be a Many2many selector."""
    _name = 'call.campaign.quality'
    _description = 'Campaign Quality Filter Option'

    name = fields.Char(string='Label', required=True)
    value = fields.Char(string='Value', required=True)

    @api.model
    def _ensure_defaults(self):
        for val, label in QUALITY_SELECTION:
            if not self.search([('value', '=', val)], limit=1):
                self.create({'name': label, 'value': val})


class LeadsLogicCampaign(models.Model):
    _inherit = 'leads.logic'

    campaign_call_done = fields.Boolean(
        string='Campaign Called', default=False,
    )
    campaign_ids = fields.Many2many(
        'call.campaign', 'call_campaign_lead_rel', 'lead_id', 'campaign_id',
        string='Campaigns'
    )
