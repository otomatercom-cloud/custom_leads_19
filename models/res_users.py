from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    voxbay_user_no = fields.Char(string='Voxbay Extension Number')
    bonvoice_agent_number = fields.Char(string='Bourn Voice Agent Number')
