# Give every existing hiring lead its private application-form link.
import secrets

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    leads = env['leads.logic'].with_context(active_test=False).search(
        [('is_hiring', '=', True), ('hiring_form_token', '=', False)])
    for lead in leads:
        lead.hiring_form_token = secrets.token_urlsafe(16)
