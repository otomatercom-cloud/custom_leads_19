"""Demo data loader / remover for Leads Management.

Creates (idempotently) demo users for EVERY role, 2 demo teams, sources,
campaigns, courses, ~40 leads with calls / responses / follow-ups and some
re-attempts, so the whole module can be shown without real data.

Everything created is registered as ir.model.data `custom_leads_19.demo_*`,
so `remove()` deletes exactly what `load()` created and nothing else.
Triggered from Settings > Leads > Demo Data (Settings administrators only).
"""
import random
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

MODULE = 'custom_leads_19'
DEMO_PASSWORD = 'Demo@1234'
DOMAIN = 'demo.otomater.com'

# key, name, role flags (lead.user.permission fields)
DEMO_USERS = [
    ('superadmin', 'Demo Super Admin', ['perm_super_admin', 'perm_manager']),
    ('manager', 'Demo Manager', ['perm_manager', 'perm_reattempt_manager']),
    ('branchhead', 'Demo Branch Head', ['perm_branch_head']),
    ('digitalhead', 'Demo Digital Head', ['perm_digital_head']),
    ('digitalteam', 'Demo Digital Team', ['perm_digital_team']),
    ('tl_kochi', 'Anil Kumar (Team Lead Kochi)', ['perm_team_lead', 'perm_reattempt_tl']),
    ('tl_calicut', 'Divya Nair (Team Lead Calicut)', ['perm_team_lead', 'perm_reattempt_tl']),
    ('ao1', 'Rahul Menon (Officer Kochi)', ['perm_officer', 'perm_reattempt_user']),
    ('ao2', 'Anjali Pillai (Officer Kochi)', ['perm_officer', 'perm_reattempt_user']),
    ('ao3', 'Sreejith K (Officer Kochi)', ['perm_officer', 'perm_reattempt_user']),
    ('ao4', 'Fathima Rahman (Officer Calicut)', ['perm_officer', 'perm_reattempt_user']),
    ('ao5', 'Arun Raj (Officer Calicut)', ['perm_officer', 'perm_reattempt_user']),
    ('ao6', 'Neethu Mohan (Officer Calicut)', ['perm_officer', 'perm_reattempt_user']),
    ('tele1', 'Demo Tele Caller 1', ['perm_tele_caller']),
    ('tele2', 'Demo Tele Caller 2', ['perm_tele_caller']),
    ('crashhead', 'Demo Crash Head', ['perm_crash_head']),
    ('crashuser', 'Demo Crash User', ['perm_crash_user']),
]
TEAMS = [
    ('team_kochi', 'Demo Team - Kochi', 'tl_kochi', ['ao1', 'ao2', 'ao3']),
    ('team_calicut', 'Demo Team - Calicut', 'tl_calicut', ['ao4', 'ao5', 'ao6']),
]
SOURCES = {
    'src_meta': ('Demo - Meta Ads', True, ['Demo Meta - CA Weekend', 'Demo Meta - ACCA Scholarship']),
    'src_google': ('Demo - Google Ads', True, ['Demo Google - CMA USA Search']),
    'src_walkin': ('Demo - Walk In', False, []),
    'src_website': ('Demo - Website', True, ['Demo Website - Brochure Download']),
}
COURSES = ['Demo - CA Foundation', 'Demo - ACCA', 'Demo - CMA USA', 'Demo - Digital Marketing']
FIRST = ['Aswin', 'Meera', 'Nikhil', 'Sneha', 'Adithya', 'Lakshmi', 'Vishnu', 'Gayathri', 'Akhil', 'Remya',
         'Jishnu', 'Athira', 'Midhun', 'Parvathy', 'Sanjay', 'Keerthi', 'Basil', 'Nimisha', 'Abhijith', 'Devika']
LAST = ['Nair', 'Menon', 'Kurian', 'Thomas', 'Varghese', 'Pillai', 'Krishnan', 'Joseph', 'Mathew', 'Das']
PLACES = ['Kochi', 'Calicut', 'Thrissur', 'Kannur', 'Palakkad', 'Kottayam', 'Malappuram', 'Alappuzha']
QUALITIES = (['new'] * 8 + ['first_attempt'] * 5 + ['hot'] * 6 + ['warm'] * 6 + ['cold'] * 3 + ['not_responding'] * 4 +
             ['follow_up'] * 4 + ['call_later'] * 2 + ['admission'] * 4 + ['not_interested'] * 2)
STATE_OF = {'new': 'new', 'first_attempt': 'in_progress', 'hot': 'in_progress', 'warm': 'in_progress',
            'cold': 'in_progress', 'not_responding': 'in_progress', 'follow_up': 'in_progress',
            'call_later': 'in_progress', 'admission': 'qualified', 'not_interested': 'lost'}
REMARKS = ['Interested, asked for fee details', 'Will discuss with parents and call back',
           'Wants weekend batch', 'Asked about scholarship', 'Comparing with another institute',
           'Ready to visit the campus this week', 'Phone busy, try evening', 'Shared brochure on WhatsApp']


class LeadDemoData(models.AbstractModel):
    _name = 'lead.demo.data'
    _description = 'Leads Demo Data Loader'

    # ------------------------------------------------------------------ helpers
    @api.model
    def _demo_check_admin(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only Settings administrators can load or remove demo data.'))

    @api.model
    def _demo_ref(self, key):
        return self.env.ref('%s.demo_%s' % (MODULE, key), raise_if_not_found=False)

    @api.model
    def _demo_reg(self, rec, key):
        self.env['ir.model.data'].sudo().create({
            'module': MODULE, 'name': 'demo_%s' % key, 'model': rec._name,
            'res_id': rec.id, 'noupdate': True})
        return rec

    @api.model
    def _demo_get(self, model, key, vals):
        rec = self._demo_ref(key)
        if rec and rec.exists():
            return rec
        return self._demo_reg(self.env[model].create(vals), key)

    @api.model
    def _demo_admission_student(self, lead, n, owner_user, owner_key):
        """Like the Admission wizard: an admitted lead gets a Student Details profile
        (and enrolment + payment when a batch / fee structure exists)."""
        env = self.env
        if 'student.details' not in env:
            return
        batch = env['student.batch'].sudo().search([('active', '=', True)], limit=1)
        student = env['student.details'].sudo().create({
            'name': lead.name, 'lead_reference_no': lead.reference_no, 'email': lead.email_address,
            'phone': lead.phone_number, 'whatsapp_number': lead.phone_number, 'city': lead.place,
            'branch': 'kochi' if owner_key in ('ao1', 'ao2', 'ao3') else 'calicut',
            'admission_officer_id': owner_user.id, 'joining_status': 'new',
            'batch_id': batch.id or False, 'lead_id': lead.id,
        })
        self._demo_reg(student, 'student_lead_%d' % n)
        vals = {'student_id': student.id, 'student_profile_created': True, 'adm_id': student.id,
                'student_name': student.name}
        if 'student_id' in lead._fields:
            vals['student_id'] = student.id
        lead.sudo().write({k: v for k, v in vals.items() if k in lead._fields})
        fee = env['fee.structure'].sudo().search([('active', '=', True), ('fee_type', '!=', 'admission')], limit=1) \
            if 'fee.structure' in env else False
        if batch and fee:
            total = fee.total_fee_amount if fee.fee_type == 'installment' else fee.amount_inclusive
            enr = env['student.enrollment'].sudo().create({
                'student_id': student.id, 'batch_id': batch.id, 'fee_structure_id': fee.id,
                'total_fee': total, 'fee_type': fee.fee_type, 'gst_rate': fee.gst_rate})
            self._demo_reg(enr, 'student_enr_%d' % n)
            pay = env['student.fee.payment'].sudo().create({
                'enrollment_id': enr.id, 'amount': round(total * 0.3, 2), 'payment_mode': 'upi',
                'remarks': 'Demo admission fee from lead %s' % lead.reference_no})
            self._demo_reg(pay, 'student_pay_%d' % n)

    # --------------------------------------------------------------------- load
    @api.model
    def load(self):
        self._demo_check_admin()
        env = self.with_context(otm_demo_load=True, otm_odoo17_import=True, tracking_disable=True,
                                mail_create_nolog=True, mail_notrigger=True, no_reset_password=True).env
        self = self.with_env(env)
        rnd = random.Random(2026)
        Users, Emp = env['res.users'].sudo(), env['hr.employee'].sudo()
        base_user = env.ref('base.group_user')

        users, emps = {}, {}
        for key, name, flags in DEMO_USERS:
            login = 'demo.%s@%s' % (key, DOMAIN)
            user = self._demo_ref('user_' + key)
            if not user or not user.exists():
                user = Users.search([('login', '=', login)], limit=1) or Users.create({
                    'name': name, 'login': login, 'email': login, 'password': DEMO_PASSWORD,
                    'group_ids': [(6, 0, [base_user.id])]})
                self._demo_reg(user, 'user_' + key)
            users[key] = user
            emp = Emp.search([('user_id', '=', user.id)], limit=1)
            if not emp:
                emp = Emp.create({'name': name, 'user_id': user.id, 'work_email': login})
                self._demo_reg(emp, 'emp_' + key)
            emps[key] = emp
            perm = self._demo_ref('perm_' + key)
            if not perm or not perm.exists():
                vals = {'user_id': user.id, 'notes': 'Demo user'}
                vals.update({f: True for f in flags})
                existing = env['lead.user.permission'].sudo().search([('user_id', '=', user.id)], limit=1)
                if existing:
                    existing.write({f: True for f in flags})
                else:
                    self._demo_reg(env['lead.user.permission'].sudo().create(vals), 'perm_' + key)

        teams = {}
        for key, name, tl, members in TEAMS:
            teams[key] = self._demo_get('lead.team', key, {
                'name': name, 'description': 'Demo team',
                'team_lead_ids': [(6, 0, [emps[tl].id])],
                'member_ids': [(0, 0, {'employee_id': emps[m].id, 'team_lead_id': emps[tl].id}) for m in members],
            })

        sources, campaigns = {}, {}
        for key, (name, digital, camps) in SOURCES.items():
            sources[key] = self._demo_get('leads.sources', key, {
                'name': name, 'digital_lead': digital, 'source': 'inbound_source'})
            for i, cname in enumerate(camps):
                campaigns[(key, i)] = self._demo_get('lead.source.campaign', '%s_c%d' % (key, i), {
                    'name': cname, 'lead_source_id': sources[key].id})
        for i, cname in enumerate(COURSES):
            self._demo_get('course.interested', 'course_%d' % i, {'name': cname})

        self._demo_get('lead.assignment.rule', 'rule_rr', {
            'name': 'Demo - Round Robin (All Teams)', 'assignment_type': 'all_teams',
            'active': False})   # inactive on purpose: enable it only during the demo

        officers = ['ao1', 'ao2', 'ao3', 'ao4', 'ao5', 'ao6']
        src_keys = list(SOURCES)
        now = fields.Datetime.now()
        leads = []
        for n in range(1, 41):
            if self._demo_ref('lead_%d' % n):
                leads.append(self._demo_ref('lead_%d' % n))
                continue
            q = 'admission' if n in (5, 15, 25, 35) else rnd.choice(QUALITIES)
            owner_key = officers[(n - 1) % 6]
            sk = src_keys[n % len(src_keys)]
            camp_ids = [c for (k, i), c in campaigns.items() if k == sk]
            age = rnd.randint(0, 20)
            created = now - timedelta(days=age, hours=rnd.randint(0, 8), minutes=rnd.randint(0, 59))
            vals = {
                'name': '%s %s' % (rnd.choice(FIRST), rnd.choice(LAST)),
                'phone_number': '9000000%03d' % n,
                'email_address': 'demo.lead%d@example.com' % n,
                'leads_source': sources[sk].id,
                'source_campaign_id': rnd.choice(camp_ids).id if camp_ids else False,
                'course_interested': 'Demo - ' + rnd.choice(['CA Foundation', 'ACCA', 'CMA USA', 'Digital Marketing']),
                'place': rnd.choice(PLACES),
                'lead_quality': q,
                'state': STATE_OF[q],
                'lead_owner': emps[owner_key].id,
                'lead_creator_id': users['digitalteam'].id,
                'tele_caller_id': users['tele1' if n % 2 else 'tele2'].id if n % 3 == 0 else False,
            }
            if q == 'admission':
                vals['admission_date'] = created + timedelta(days=1)
            lead = env['leads.logic'].sudo().create(vals)
            self._demo_reg(lead, 'lead_%d' % n)
            env.cr.execute("UPDATE leads_logic SET create_date=%s, write_date=%s, date_of_adding=%s, "
                           "last_update_date=%s WHERE id=%s",
                           (created, created, created.date(), created, lead.id))
            leads.append(lead)
            owner_user = users[owner_key]
            if q == 'admission':
                self._demo_admission_student(lead, n, owner_user, owner_key)

            for _i in range(rnd.randint(0, 3)):      # call logs
                answered = rnd.random() > 0.35
                env['lead.call.log'].sudo().create({
                    'lead_id': lead.id, 'user_id': owner_user.id,
                    'call_time': created + timedelta(hours=rnd.randint(1, 30)),
                    'call_type': rnd.choice(['outgoing', 'outgoing', 'incoming']),
                    'call_status': 'ANSWERED' if answered else 'NO ANSWER',
                    'duration': '00:%02d:%02d' % (rnd.randint(0, 6), rnd.randint(0, 59)) if answered else '00:00:00',
                    'caller_number': lead.phone_number, 'remarks': rnd.choice(REMARKS)})
            if rnd.random() > 0.4:                   # responses
                env['lead.response'].sudo().create({
                    'lead_id': lead.id, 'user_id': owner_user.id, 'comment': rnd.choice(REMARKS),
                    'response_time': created + timedelta(hours=2)})
            if q in ('hot', 'warm', 'follow_up', 'call_later'):   # follow-ups: overdue / today / tomorrow
                when = [now - timedelta(days=2), now + timedelta(hours=rnd.randint(1, 6)),
                        now + timedelta(days=1)][n % 3]
                env['lead.followup'].sudo().create({
                    'lead_id': lead.id, 'user_id': owner_user.id, 'next_followup_date': when,
                    'phone_number': lead.phone_number, 'remarks': rnd.choice(REMARKS), 'status': 'scheduled'})

        for i, (lead_idx, officer) in enumerate([(2, 'ao4'), (7, 'ao1'), (12, 'ao5'), (19, 'ao2')], 1):
            if self._demo_ref('reattempt_%d' % i):
                continue
            lead = leads[lead_idx]
            other = sources['src_google' if lead.leads_source != sources['src_google'] else 'src_meta']
            self._demo_reg(env['otomater.lead.reattempt'].sudo().create({
                'lead_id': lead.id, 'existing_owner_id': lead.lead_owner.id,
                'requested_owner_id': emps[officer].id, 'source_id': other.id,
                'duplicate_type': 'phone', 'mobile': lead.phone_number,
                'remarks': 'Demo: same student enquired again via %s' % other.name,
                'review_status': 'pending_review'}), 'reattempt_%d' % i)
        return True

    # ------------------------------------------------------------------- remove
    @api.model
    def remove(self):
        self._demo_check_admin()
        env = self.with_context(otm_demo_load=True, tracking_disable=True).env
        IMD = env['ir.model.data'].sudo()
        rows = IMD.search([('module', '=', MODULE), ('name', '=like', 'demo\\_%')])
        by_model = {}
        for r in rows:
            by_model.setdefault(r.model, []).append(r.res_id)
        order = ['otomater.lead.reattempt', 'student.fee.payment', 'student.enrollment', 'student.details', 'leads.logic', 'lead.assignment.rule', 'lead.team',
                 'lead.user.permission', 'hr.employee', 'res.users', 'lead.source.campaign',
                 'leads.sources', 'course.interested']
        archived = []
        for model in order:
            if model not in env:
                continue
            recs = env[model].sudo().with_context(active_test=False).browse(by_model.get(model, [])).exists()
            if model == 'leads.logic':
                recs.with_context(otm_demo_load=True).unlink()
                continue
            if model in ('res.users', 'hr.employee'):
                for rec in recs:                         # users/employees with history are archived instead
                    try:
                        with env.cr.savepoint():
                            rec.unlink()
                    except Exception:
                        rec.write({'active': False})
                        archived.append(rec.display_name)
                continue
            recs.unlink()
        rows.unlink()
        return archived
