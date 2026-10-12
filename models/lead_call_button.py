# -*- coding: utf-8 -*-
"""One "Call" button on the lead: uses Voxbay or Bonvoice (whichever is set up) and logs the call,
so the recording and duration arrive later through the provider's webhook."""
from odoo import _, fields, models
from odoo.exceptions import UserError

P_PROVIDER = 'custom_leads_19.call_provider'


class ResConfigSettingsCallProvider(models.TransientModel):
    _inherit = 'res.config.settings'

    call_provider = fields.Selection(
        [('auto', 'Automatic (Bonvoice / Voxbay if set up for the officer, else the phone app)'),
         ('softphone', 'Softphone or phone app (MicroSIP, Zoiper, phone dialler)'),
         ('voxbay', 'Voxbay'), ('bonvoice', 'Bonvoice')],
        string='Call button uses', config_parameter=P_PROVIDER, default='auto',
        help='Which calling service the Call button on a lead uses.')
    dial_scheme = fields.Selection(
        [('tel', 'tel: (works with most softphones and phones)'), ('sip', 'sip: (MicroSIP, Zoiper, Linphone)')],
        string='Phone app link', config_parameter='custom_leads_19.dial_scheme', default='tel',
        help='Link type opened on the computer or phone when the Softphone option is used.')


class LeadsLogicCallButton(models.Model):
    _inherit = 'leads.logic'

    def _call_provider_for_user(self):
        company, user = self.env.company, self.env.user
        vox = bool(company.voxbay_uid and company.voxbay_upin and company.voxbay_callerid and user.voxbay_user_no)
        bon = bool(company.bonvoice_username and company.bonvoice_password and user.bonvoice_agent_number)
        pref = self.env['ir.config_parameter'].sudo().get_param(P_PROVIDER) or 'auto'
        if pref == 'softphone':
            return 'softphone'
        if pref == 'voxbay':
            return 'voxbay' if vox else False
        if pref == 'bonvoice':
            return 'bonvoice' if bon else False
        return 'bonvoice' if bon else ('voxbay' if vox else 'softphone')

    def action_call_lead(self):
        """Dial the lead from the officer's phone through the configured service."""
        self.ensure_one()
        provider = self._call_provider_for_user()
        if provider == 'bonvoice':
            return self.action_bonvoice_call()
        if provider == 'voxbay':
            return self.action_voxbay_call()
        if provider == 'softphone':
            return self.action_kanban_start_call()   # opens the softphone / phone app and the call timer
        raise UserError(_("The selected calling service is not set up for you. Ask your manager to fill the "
                          "details in Settings and your extension / agent number on your user profile."))
