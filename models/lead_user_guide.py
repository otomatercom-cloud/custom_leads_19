# -*- coding: utf-8 -*-
"""Switch (Settings > Leads > User guide) that shows the Lead User Guide menu to every internal user."""
from odoo import fields, models


class ResConfigSettingsLeadGuide(models.TransientModel):
    _inherit = 'res.config.settings'

    lead_guide_enabled = fields.Boolean(
        string='Show the user guide menu', implied_group='custom_leads_19.group_lead_guide',
        help='Adds the "Lead User Guide" menu for every user. Switch off to hide it again.')
