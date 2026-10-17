# The Crash Course option starts ON (switch it off in Settings > Leads > Crash Course).
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref('custom_leads_19.group_crash_course_on', raise_if_not_found=False)
    if group:
        env.ref('base.group_user').write({'implied_ids': [(4, group.id)]})
