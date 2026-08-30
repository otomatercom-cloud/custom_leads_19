from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    voxbay_uid = fields.Char(string='Voxbay UID')
    voxbay_upin = fields.Char(string='Voxbay UPIN')
    voxbay_callerid = fields.Char(string='Voxbay Caller ID (DID)')

    bonvoice_username = fields.Char(string='Bonvoice Username')
    bonvoice_password = fields.Char(string='Bonvoice Password')
    bonvoice_leg_a_caller_id = fields.Char(string='Bonvoice Leg A Caller ID')
    bonvoice_leg_b_caller_id = fields.Char(string='Bonvoice Leg B Caller ID')
    bonvoice_url = fields.Char(
        string='Bonvoice Auto Call API URL',
        default='https://backend.pbx.bonvoice.com/autoDialManagement/autoCallBridging/'
    )

    meta_verify_token = fields.Char(string='Meta Verify Token')
    meta_page_access_token = fields.Char(string='Meta Page Access Token')

    auto_create_lead_incoming = fields.Boolean(
        string='Auto-Create Lead on Unknown Incoming Call', default=True,
        help="When an incoming Voxbay call comes from a number that matches no existing "
             "lead, automatically create one under source 'Incoming Call Leads'. "
             "When off, the call is still logged, just without a lead attached.")
    auto_create_lead_outgoing = fields.Boolean(
        string='Auto-Create Lead on Unknown Outgoing Call', default=False,
        help="When an outgoing Voxbay call is dialed to a number that matches no existing "
             "lead, automatically create one under source 'Outgoing Call Leads'. "
             "When off, the call is still logged, just without a lead attached.")
