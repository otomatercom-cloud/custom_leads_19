# Re-compute the stored "Assigned After / Called After" texts so old values also show days.
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Lead = env['leads.logic'].with_context(active_test=False)
    ids = Lead.search([]).ids
    for i in range(0, len(ids), 500):
        batch = Lead.browse(ids[i:i + 500])
        batch._compute_response_times()
        batch.flush_recordset()
        batch.invalidate_recordset()
