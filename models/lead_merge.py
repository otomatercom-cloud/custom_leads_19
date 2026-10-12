# -*- coding: utf-8 -*-
"""Duplicate lead merge: find leads sharing a mobile number and merge them into one, keeping every
call, follow-up, counselling session, history entry, message and file."""
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

SKIP_FIELDS = {'id', 'create_date', 'create_uid', 'write_date', 'write_uid', 'reference_no', '__last_update',
               'display_name', 'message_ids', 'message_follower_ids', 'activity_ids', 'call_score',
               'auto_reassign_count', 'odoo17_lead_id', 'odoo17_import_log_id'}
FILL_TYPES = ('char', 'text', 'integer', 'float', 'date', 'datetime', 'selection', 'many2one', 'binary', 'html')


class LeadMergeLog(models.Model):
    _name = 'lead.merge.log'
    _description = 'Merged duplicate lead (audit)'
    _order = 'id desc'

    master_id = fields.Many2one('leads.logic', string='Kept lead', ondelete='set null')
    master_ref = fields.Char(string='Kept reference')
    merged_ref = fields.Char(string='Removed reference')
    merged_name = fields.Char(string='Removed name')
    merged_phone = fields.Char(string='Phone')
    merged_created = fields.Datetime(string='Removed lead created')
    merged_owner = fields.Char(string='Removed lead officer')
    moved = fields.Char(string='Moved to the kept lead')
    user_id = fields.Many2one('res.users', string='Merged by', default=lambda s: s.env.user)


class LeadMergeLine(models.TransientModel):
    _name = 'lead.merge.line'
    _description = 'Duplicate group'
    _order = 'count desc, id'

    wizard_id = fields.Many2one('lead.merge.wizard', ondelete='cascade')
    phone = fields.Char(string='Mobile (last 10 digits)')
    lead_ids = fields.Many2many('leads.logic', 'lead_merge_line_lead_rel', 'line_id', 'lead_id', string='Leads')
    count = fields.Integer(string='Leads')
    master_id = fields.Many2one('leads.logic', string='Keep this lead',
                                domain="[('id', 'in', lead_ids)]")
    done = fields.Boolean()

    def action_merge(self):
        self.ensure_one()
        self.env['lead.merge.wizard']._merge_group(self.master_id, self.lead_ids - self.master_id)
        self.done = True
        return {'type': 'ir.actions.act_window', 'res_model': 'lead.merge.wizard',
                'res_id': self.wizard_id.id, 'view_mode': 'form', 'target': 'new'}


class LeadMergeWizard(models.TransientModel):
    _name = 'lead.merge.wizard'
    _description = 'Merge duplicate leads'

    min_leads = fields.Integer(string='At least this many leads with the same number', default=2)
    line_ids = fields.One2many('lead.merge.line', 'wizard_id', string='Duplicate groups')
    note = fields.Char(readonly=True)

    @api.model
    def _check_access(self):
        u = self.env.user
        if not (u.has_group('custom_leads_19.group_lead_manager') or u.has_group('custom_leads_19.group_super_admin')):
            raise AccessError(_('Only managers can merge leads.'))

    @api.model
    def _best_master(self, leads):
        """Admission first, then most calls, then the oldest."""
        return sorted(leads, key=lambda l: (not l.admission_status, -l.call_count, l.id))[0]

    def action_find(self):
        self._check_access()
        self.ensure_one()
        self.line_ids.unlink()
        self.env.cr.execute("""
            SELECT RIGHT(REGEXP_REPLACE(phone_number, '\\D', '', 'g'), 10) AS p, ARRAY_AGG(id ORDER BY id)
              FROM leads_logic
             WHERE phone_number IS NOT NULL AND LENGTH(REGEXP_REPLACE(phone_number, '\\D', '', 'g')) >= 10
          GROUP BY p HAVING COUNT(*) >= %s
          ORDER BY COUNT(*) DESC, p LIMIT 200""", (max(self.min_leads, 2),))
        rows = self.env.cr.fetchall()
        Lead = self.env['leads.logic'].sudo()
        for phone, ids in rows:
            leads = Lead.browse(ids)
            self.env['lead.merge.line'].create({
                'wizard_id': self.id, 'phone': phone, 'lead_ids': [(6, 0, ids)], 'count': len(ids),
                'master_id': self._best_master(leads).id})
        self.note = _('%s group(s) found (first 200 shown).') % len(rows)
        return self._reopen()

    def action_merge_all(self):
        """Merge every open group into its suggested lead."""
        self._check_access()
        n = 0
        for line in self.line_ids.filtered(lambda l: not l.done and l.master_id):
            self._merge_group(line.master_id, line.lead_ids - line.master_id)
            line.done = True
            n += 1
        self.note = _('%s group(s) merged.') % n
        return self._reopen()

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'lead.merge.wizard', 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    # ───────────────────────── the merge itself ─────────────────────────
    @api.model
    def _child_fields(self):
        """Stored many2one fields (any module) that point to leads.logic."""
        out = []
        for model in self.env.registry.values():
            if model._name in ('leads.logic', 'lead.merge.line', 'lead.merge.log') or model._transient or model._abstract:
                continue
            for fname, f in model._fields.items():
                if f.type == 'many2one' and f.comodel_name == 'leads.logic' and f.store and not f.related \
                        and not f.compute:
                    out.append((model._name, fname))
        return out

    @api.model
    def _merge_group(self, master, dups):
        self._check_access()
        master, dups = master.sudo(), dups.sudo()
        if not master or not dups or master in dups:
            raise UserError(_('Pick the lead to keep.'))
        cr = self.env.cr
        for dup in dups:
            moved = []
            with cr.savepoint():
                # 1. every record that points at the duplicate now points at the kept lead
                for model, fname in self._child_fields():
                    recs = self.env[model].sudo().with_context(active_test=False).search([(fname, '=', dup.id)])
                    if recs:
                        recs.write({fname: master.id})
                        moved.append('%s %s' % (len(recs), self.env[model]._description or model))
                # 2. chatter, activities
                cr.execute("UPDATE mail_message SET res_id = %s WHERE model = 'leads.logic' AND res_id = %s",
                           (master.id, dup.id))
                cr.execute("UPDATE mail_activity SET res_id = %s WHERE res_model = 'leads.logic' AND res_id = %s",
                           (master.id, dup.id))
                cr.execute("DELETE FROM mail_followers WHERE res_model = 'leads.logic' AND res_id = %s", (dup.id,))
                cr.execute("UPDATE ir_attachment SET res_id = %s WHERE res_model = 'leads.logic' AND res_id = %s AND res_field IS NULL",
                           (master.id, dup.id))
                # 3. courses are added, empty fields are filled from the duplicate
                if dup.course_inter - master.course_inter:
                    master.course_inter = [(4, c.id) for c in dup.course_inter]
                fill = {}
                for fname, f in master._fields.items():
                    if (fname in SKIP_FIELDS or f.type not in FILL_TYPES or not f.store or f.compute or f.related
                            or f.readonly):
                        continue
                    if not master[fname] and dup[fname]:
                        fill[fname] = dup[fname].id if f.type == 'many2one' else dup[fname]
                if fill:
                    try:
                        with cr.savepoint():
                            master.with_context(skip_pool_rules=True, tracking_disable=True).write(fill)
                    except Exception:  # noqa: BLE001 - keep the merge; just skip the fill
                        _logger.exception('Merge: could not fill fields from %s', dup.reference_no)
                # 4. audit, note, remove
                self.env['lead.merge.log'].create({
                    'master_id': master.id, 'master_ref': master.reference_no, 'merged_ref': dup.reference_no,
                    'merged_name': dup.name, 'merged_phone': dup.phone_number, 'merged_created': dup.create_date,
                    'merged_owner': dup.lead_owner.name or '', 'moved': ', '.join(moved)})
                master.message_post(body=_('Merged duplicate lead %(ref)s (%(name)s, created %(date)s, officer %(owner)s). '
                                           'Moved: %(moved)s') % {
                    'ref': dup.reference_no, 'name': dup.name or '', 'date': dup.create_date,
                    'owner': dup.lead_owner.name or '-', 'moved': ', '.join(moved) or '-'})
                dup.unlink()
        master.invalidate_recordset()
        return True
