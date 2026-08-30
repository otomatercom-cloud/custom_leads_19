import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LeadCampaignBulkWizard(models.TransientModel):
    """
    Bulk-add selected leads (from the leads list view) directly into a
    call center campaign, so an officer/manager can multi-select leads
    in the tree and either drop them into an existing campaign or spin
    up a brand new one for calling — without going through the
    campaign's own "Load Leads" filter screen.
    """
    _name = 'lead.campaign.bulk.wizard'
    _description = 'Add Leads to Call Campaign'

    lead_ids = fields.Many2many(
        'leads.logic',
        string='Leads',
        default=lambda self: self.env.context.get('active_ids', []),
    )
    lead_count = fields.Integer(string='Selected Leads', compute='_compute_lead_count')

    mode = fields.Selection([
        ('existing', 'Add to Existing Campaign'),
        ('new', 'Create New Campaign'),
    ], string='Mode', default='existing', required=True)

    campaign_id = fields.Many2one(
        'call.campaign',
        string='Campaign',
        domain="[('state', 'in', ['draft', 'running'])]",
        help='Only Draft or Running campaigns are shown — leads cannot be added to a Completed/Cancelled campaign.',
    )
    new_campaign_name = fields.Char(string='New Campaign Name')

    @api.depends('lead_ids')
    def _compute_lead_count(self):
        for wiz in self:
            wiz.lead_count = len(wiz.lead_ids)

    @api.onchange('mode')
    def _onchange_mode(self):
        # Avoid keeping a stale value from the other mode
        if self.mode == 'existing':
            self.new_campaign_name = False
        else:
            self.campaign_id = False

    def action_add(self):
        self.ensure_one()

        leads = self.lead_ids or self.env['leads.logic'].browse(
            self.env.context.get('active_ids', [])
        )
        if not leads:
            raise UserError(_('No leads selected. Select leads from the list view first.'))

        if self.mode == 'new':
            if not self.new_campaign_name:
                raise UserError(_('Please enter a name for the new campaign.'))
            # Creating a campaign is normally Manager/Super-Admin-only
            # (see ir.model.access.csv); this wizard's own access is the
            # intended gate for the "quick campaign from selected leads"
            # shortcut, so the create is scoped narrowly under sudo()
            # rather than widening call.campaign's own create ACL.
            campaign = self.env['call.campaign'].sudo().create({
                'name': self.new_campaign_name,
                'state': 'draft',
            })
        else:
            if not self.campaign_id:
                raise UserError(_('Please select a campaign.'))
            campaign = self.campaign_id
            if campaign.state not in ('draft', 'running'):
                raise UserError(_(
                    'Campaign "%(name)s" is %(state)s — leads can only be added '
                    'to a Draft or Running campaign.',
                    name=campaign.name, state=campaign.state,
                ))

        existing_ids = set(campaign.lead_ids.ids)
        new_leads = leads.filtered(lambda l: l.id not in existing_ids)

        if new_leads:
            campaign.sudo().write({'lead_ids': [(4, lead.id) for lead in new_leads]})

        added = len(new_leads)
        skipped = len(leads) - added

        if added:
            message = _(
                '%(count)s lead(s) added to campaign "%(name)s".',
                count=added, name=campaign.name,
            )
            if skipped:
                message += ' ' + _(
                    '%(skipped)s lead(s) were already in the campaign.', skipped=skipped,
                )
            msg_type = 'success'
        else:
            message = _('All selected leads were already in campaign "%(name)s".', name=campaign.name)
            msg_type = 'warning'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Added to Call Campaign'),
                'message': message,
                'type': msg_type,
                'sticky': True,
            },
        }
