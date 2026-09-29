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
    campaign_ids = fields.One2many('lead.source.campaign', 'lead_source_id', string='Campaigns')
    campaign_count = fields.Integer(string='Campaign Count', compute='_compute_campaign_count')

    @api.depends('campaign_ids')
    def _compute_campaign_count(self):
        for rec in self:
            rec.campaign_count = len(rec.campaign_ids)


class LeadSourceCampaign(models.Model):
    """Source Campaign - child of a Lead Source (same model as Odoo 17)."""
    _name = 'lead.source.campaign'
    _description = 'Lead Source Campaign'
    _order = 'sequence, name'

    name = fields.Char('Name', required=True)
    sequence = fields.Integer('Sequence', default=10)
    active = fields.Boolean('Active', default=True)
    lead_source_id = fields.Many2one('leads.sources', string='Parent Lead Source', index=True)
