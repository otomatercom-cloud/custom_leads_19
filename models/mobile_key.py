# -*- coding: utf-8 -*-
"""Phone-app key: every officer makes their own key (no Odoo API-key permission needed)."""
import hashlib
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError


def hash_key(key):
    return hashlib.sha256((key or '').strip().encode()).hexdigest()


class OtmMobileKey(models.Model):
    _name = 'otm.mobile.key'
    _description = 'Phone app key'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    key_hash = fields.Char(required=True, index=True, copy=False)
    hint = fields.Char(string='Key ends with')
    active = fields.Boolean(default=True)
    last_seen = fields.Datetime(string='Last sync')

    @api.model
    def user_for_key(self, key):
        """res.users id for a valid key (and note the time it was used), else False."""
        if not key:
            return False
        rec = self.sudo().search([('key_hash', '=', hash_key(key)), ('active', '=', True)], limit=1)
        if not rec or not rec.user_id.active:
            return False
        if not rec.last_seen or (fields.Datetime.now() - rec.last_seen).total_seconds() > 300:
            rec.last_seen = fields.Datetime.now()
        return rec.user_id.id


class OtmMobileKeyWizard(models.TransientModel):
    _name = 'otm.mobile.key.wizard'
    _description = 'Make my phone app key'

    key = fields.Char(string='Your key', readonly=True)
    server = fields.Char(string='Odoo address', readonly=True, compute='_compute_server')

    def _compute_server(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        for rec in self:
            rec.server = base

    def action_generate(self):
        self.ensure_one()
        if self.env.user.share:
            raise UserError(_('Only internal users can make a phone app key.'))
        Key = self.env['otm.mobile.key'].sudo()
        Key.search([('user_id', '=', self.env.uid)]).write({'active': False})   # a new key replaces the old one
        key = 'otm_' + secrets.token_urlsafe(24)
        Key.create({'user_id': self.env.uid, 'key_hash': hash_key(key), 'hint': key[-4:]})
        self.key = key
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new'}
