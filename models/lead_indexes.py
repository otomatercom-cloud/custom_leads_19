# -*- coding: utf-8 -*-
"""Database indexes for the columns the Leads screens, assignment engine and reports filter on.
Created with IF NOT EXISTS and skipped when the table / column is missing or already indexed."""
import logging

from odoo import models

_logger = logging.getLogger(__name__)

# (index suffix, table, "column list / expression", optional WHERE)
INDEXES = [
    ('owner', 'leads_logic', 'lead_owner', ''),
    ('source', 'leads_logic', 'leads_source', ''),
    ('quality', 'leads_logic', 'lead_quality', ''),
    ('state', 'leads_logic', 'state', ''),
    ('team', 'leads_logic', 'team_id', ''),
    ('stage', 'leads_logic', 'lead_stage_category', ''),
    ('created', 'leads_logic', 'create_date', ''),
    ('owner_id', 'leads_logic', 'lead_owner, id DESC', ''),
    ('owner_created', 'leads_logic', 'lead_owner, create_date DESC', ''),
    ('uncalled', 'leads_logic', 'create_date', 'first_called_dt IS NULL'),
    ('admission', 'leads_logic', 'admission_date', 'admission_status IS TRUE'),
    ('phone10', 'leads_logic', "RIGHT(REGEXP_REPLACE(phone_number, '\\D', '', 'g'), 10)", ''),
    ('lead', 'lead_call_log', 'lead_id', ''),
    ('user_time', 'lead_call_log', 'user_id, call_time', ''),
    ('time', 'lead_call_log', 'call_time', ''),
    ('lead', 'lead_followup', 'lead_id', ''),
    ('user_status', 'lead_followup', 'user_id, status, next_followup_date', ''),
    ('due', 'lead_followup', 'next_followup_date', "status = 'scheduled'"),
    ('lead', 'lead_assignment_history', 'lead_id', ''),
    ('date', 'lead_assignment_history', 'assigned_date', ''),
    ('lead_date', 'lead_quality_history', 'lead_id, change_date', ''),
    ('lead', 'lead_counselling', 'lead_id', ''),
    ('appt', 'lead_counselling', 'appointment_date', ''),
]


def _columns_in(expr):
    return [c.strip().split(' ')[0] for c in expr.split(',')] if '(' not in expr else []


def ensure_indexes(cr):
    made = 0
    for suffix, table, expr, where in INDEXES:
        try:
            cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,))
            if not cr.fetchone():
                continue
            cols = _columns_in(expr)
            if cols:
                cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s "
                           "AND column_name = ANY(%s)", (table, cols))
                if len(cr.fetchall()) != len(cols):
                    continue
                # a single plain column that already has an index (e.g. from index=True) is left alone
                if len(cols) == 1 and not where and ' ' not in expr:
                    cr.execute("SELECT 1 FROM pg_indexes WHERE tablename = %s AND indexdef ~ %s",
                               (table, r'\(%s\)' % cols[0]))
                    if cr.fetchone():
                        continue
            name = 'otm_%s_%s_idx' % (table, suffix)
            sql = 'CREATE INDEX IF NOT EXISTS %s ON %s (%s)%s' % (name, table, expr, ' WHERE ' + where if where else '')
            with cr.savepoint():
                cr.execute(sql)
            made += 1
        except Exception:  # noqa: BLE001 - an index problem must never stop the upgrade
            _logger.exception('Index %s on %s skipped', suffix, table)
    return made


class LeadsLogicIndexes(models.Model):
    _inherit = 'leads.logic'

    def init(self):
        super().init()
        ensure_indexes(self.env.cr)
