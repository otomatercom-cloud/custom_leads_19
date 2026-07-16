"""
Migration 19.0.1.1.0 -> 19.0.1.1.1
Add enable_followup_popup and enable_call_timer columns to res_company
before views are validated, to prevent ParseError on upgrade.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    # Add enable_followup_popup if not present
    cr.execute("""
        ALTER TABLE res_company
        ADD COLUMN IF NOT EXISTS enable_followup_popup BOOLEAN DEFAULT TRUE;
    """)
    # Add enable_call_timer if not present
    cr.execute("""
        ALTER TABLE res_company
        ADD COLUMN IF NOT EXISTS enable_call_timer BOOLEAN DEFAULT TRUE;
    """)
