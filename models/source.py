from odoo import fields, models, api, _


class LeadsSources(models.Model):
    _name = 'leads.sources'
    _inherit = 'mail.thread'
    _description = 'Leads Sources'

    name = fields.Char('Name', required=True, tracking=1)
    digital_lead = fields.Boolean('Digital Lead', default=False)
    source = fields.Selection(
        [('inbound_source', 'Inbound Source'), ('outbound_source', 'Outbound Source')],
        string="Source"
    )
