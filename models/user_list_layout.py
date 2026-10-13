# -*- coding: utf-8 -*-
"""Each user's own column order for the Leads lists (drag a column header to move it)."""
import json

from odoo import api, fields, models


class OtmUserListLayout(models.Model):
    _name = 'otm.user.list.layout'
    _description = 'User list column order'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    list_key = fields.Char(required=True, index=True)
    columns = fields.Text(help='JSON list of column names in the order the user chose.')

    _user_key_uniq = models.Constraint('UNIQUE(user_id, list_key)', 'One layout per user and list.')

    @api.model
    def get_layout(self, list_key):
        rec = self.sudo().search([('user_id', '=', self.env.uid), ('list_key', '=', list_key)], limit=1)
        try:
            return json.loads(rec.columns) if rec and rec.columns else []
        except ValueError:
            return []

    @api.model
    def set_layout(self, list_key, columns):
        rec = self.sudo().search([('user_id', '=', self.env.uid), ('list_key', '=', list_key)], limit=1)
        if not columns:
            rec.unlink()
            return True
        vals = {'columns': json.dumps([str(c) for c in columns][:100])}
        if rec:
            rec.write(vals)
        else:
            self.sudo().create(dict(vals, user_id=self.env.uid, list_key=list_key))
        return True
