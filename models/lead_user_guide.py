# -*- coding: utf-8 -*-
"""Switch (Settings > Leads > User guide) that shows the Lead User Guide menu to every user."""
from odoo import api, fields, models

MENU = 'custom_leads_19.menu_lead_user_guide'


class ResConfigSettingsLeadGuide(models.TransientModel):
    _inherit = 'res.config.settings'

    lead_guide_enabled = fields.Boolean(
        string='Show the user guide menu', compute='_compute_lead_guide_enabled',
        inverse='_inverse_lead_guide_enabled',
        help='Adds the "Lead User Guide" menu for every user. Switch off to hide it again.')

    def _guide_menu(self):
        return self.env.ref(MENU, raise_if_not_found=False)

    @api.depends_context('uid')
    def _compute_lead_guide_enabled(self):
        menu = self._guide_menu()
        on = bool(menu and menu.sudo().with_context(active_test=False).active)
        for rec in self:
            rec.lead_guide_enabled = on

    def _inverse_lead_guide_enabled(self):
        menu = self._guide_menu()
        if menu:
            menu.sudo().write({'active': bool(self[:1].lead_guide_enabled)})
