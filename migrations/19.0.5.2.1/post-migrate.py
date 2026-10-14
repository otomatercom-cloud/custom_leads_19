# Flag the existing "hiring" Source Campaigns (their leads then become hiring leads).
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    camps = env['lead.source.campaign'].with_context(active_test=False).search([('name', 'ilike', 'hiring')])
    camps.write({'is_hiring': True})
