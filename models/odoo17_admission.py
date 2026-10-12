# -*- coding: utf-8 -*-
"""'Admission (Odoo 17)' button: the admission process still runs in Odoo 17, so this sends the lead
(details, responses, call logs, follow-ups) to Odoo 17 and opens it there in a new tab."""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# never sent to Odoo 17 as plain values
NOT_SENT = {
    'id', 'reference_no', 'odoo17_lead_id', 'odoo17_import_log_id', 'odoo17_checked_on', 'create_uid',
    'write_uid', 'create_date', 'write_date', 'company_id', 'student_id', 'adm_id', 'masked_phone',
    'auto_reassign_count', 'last_update_date', 'lead_creator_id', 'message_main_attachment_id',
}
M2O_OK = {'res.users', 'hr.employee', 'leads.sources', 'lead.source.campaign', 'course.interested'}
CHILD_SPECS = {
    'lead.response': ['user_id', 'comment', 'response_time'],
    'lead.call.log': ['user_id', 'call_time', 'remarks', 'call_uuid', 'caller_number', 'call_status',
                      'duration', 'recording_url', 'call_type'],
    'lead.followup': ['user_id', 'next_followup_date', 'remarks', 'phone_number', 'status'],
}


def _last10(v):
    return ''.join(c for c in str(v or '') if c.isdigit())[-10:]


PARAM_BUTTON = 'custom_leads_19.odoo17_admission_button'


class ResConfigSettingsOdoo17Admission(models.TransientModel):
    _inherit = 'res.config.settings'

    odoo17_admission_button = fields.Boolean(
        string='Admission (Odoo 17) button', config_parameter=PARAM_BUTTON, default=True,
        help='Shows the 🎓 Admission (Odoo 17) button on the lead form. Turn it off when the admission '
             'process has moved to Odoo 19.')


class LeadsLogicOdoo17Admission(models.Model):
    _inherit = 'leads.logic'

    show_odoo17_admission = fields.Boolean(compute='_compute_show_odoo17_admission')

    @api.depends_context('uid')
    def _compute_show_odoo17_admission(self):
        on = self.env['ir.config_parameter'].sudo().get_param(PARAM_BUTTON) != 'False'
        for rec in self:
            rec.show_odoo17_admission = on

    def _o17_fields(self, rfields):
        """Lead fields that exist in Odoo 17 with the same type and can be sent as values."""
        out = []
        for name, f in self._fields.items():
            if name in NOT_SENT or not f.store or f.compute or f.related:
                continue
            if f.type not in ('char', 'text', 'selection', 'many2one', 'date', 'datetime', 'integer',
                              'float', 'boolean'):
                continue
            if f.type == 'many2one' and f.comodel_name not in M2O_OK:
                continue
            rf = rfields.get(name)
            if rf and rf.get('type') == f.type:
                out.append(name)
        return out

    def _o17_push_children(self, call, rid, cache):
        """New Odoo 17 lead only: copy the responses, call logs and follow-ups."""
        self.ensure_one()
        sent = {}
        for model, flds in CHILD_SPECS.items():
            if model not in self.env:
                continue
            try:
                rf = call(model, 'fields_get', attributes=['type', 'selection'])
            except Exception:  # noqa: BLE001
                continue
            Local = self.env[model].sudo()
            n = 0
            for rec in Local.search([('lead_id', '=', self.id)], order='id asc'):
                vals = {'lead_id': rid}
                for f in flds:
                    if f not in rf or f not in rec._fields:
                        continue
                    v = rec[f]
                    t = rec._fields[f].type
                    if t == 'many2one':
                        if not v:
                            continue
                        key = v.login if v._name == 'res.users' else v.display_name
                        v = self.env['otm.leads.odoo17.sync.queue']._remote_id(call, v._name, key, False, cache)
                        if not v:
                            continue
                    elif t in ('date', 'datetime'):
                        v = fields.Date.to_string(v) if t == 'date' else fields.Datetime.to_string(v)
                    elif t == 'selection' and v:
                        keys = {k for k, _l in rf[f].get('selection') or []}
                        if keys and v not in keys:
                            continue
                    if v in (False, None, ''):
                        continue
                    vals[f] = v
                try:
                    call(model, 'create', vals, context={'tracking_disable': True, 'otm_odoo19_sync': True})
                    n += 1
                except Exception as e:  # noqa: BLE001
                    _logger.warning('Odoo17 admission: %s row not sent: %s', model, str(e)[:200])
            sent[model] = n
        return sent

    def action_odoo17_admission(self):
        self.ensure_one()
        if self.env['ir.config_parameter'].sudo().get_param(PARAM_BUTTON) == 'False':
            raise UserError(_("The Admission (Odoo 17) button is turned off in Settings."))
        lead = self.sudo()
        wiz = self.env['otm.leads.odoo17.import.wizard'].sudo()
        Queue = self.env['otm.leads.odoo17.sync.queue'].sudo()
        call, _info = wiz._connect()
        cfg = wiz._get_odoo17_connection()
        base = (cfg['url'] or '').rstrip('/')
        if not base.startswith('http'):
            base = 'https://' + base
        rfields = call('leads.logic', 'fields_get', attributes=['type', 'selection'])
        cache = {}
        rid = lead.odoo17_lead_id
        action_note = ''
        if not rid:                                    # maybe the lead already exists in Odoo 17
            phone = _last10(lead.phone_number)
            if len(phone) >= 8:
                dom = [('phone_number', 'ilike', phone)]
                year = lead.academic_year_of_course_attend if 'academic_year_of_course_attend' in rfields else False
                if year:        # Odoo 17 treats the same phone in the same academic year as a duplicate
                    dom.append(('academic_year_of_course_attend', '=', year))
                ids = call('leads.logic', 'search', dom, limit=1, order='id desc',
                           context={'active_test': False})
                rid = ids[0] if ids else False
            if rid:
                action_note = _('linked to the existing Odoo 17 lead #%s') % rid
                from .odoo17_sync import SYNC_FIELDS
                fnames = [f for f in SYNC_FIELDS if f in lead._fields and f in rfields]
                vals, notes = Queue._build_vals(call, rfields, Queue._payload_for(lead, fnames), cache)
                if vals:
                    call('leads.logic', 'write', [rid], vals,
                         context={'tracking_disable': True, 'otm_odoo19_sync': True})
        else:
            from .odoo17_sync import SYNC_FIELDS
            fnames = [f for f in SYNC_FIELDS if f in lead._fields and f in rfields]
            vals, notes = Queue._build_vals(call, rfields, Queue._payload_for(lead, fnames), cache)
            if vals:
                call('leads.logic', 'write', [rid], vals,
                     context={'tracking_disable': True, 'otm_odoo19_sync': True})
            action_note = _('updated the Odoo 17 lead #%s') % rid
        if not rid:                                    # create it in Odoo 17
            fnames = self._o17_fields(rfields)
            vals, notes = Queue._build_vals(call, rfields, Queue._payload_for(lead, fnames), cache)
            if 'course_inter' in lead._fields and 'course_inter' in rfields and lead.course_inter:
                cids = [Queue._remote_id(call, 'course.interested', c.name, False, cache) for c in lead.course_inter]
                cids = [c for c in cids if c]
                if cids:
                    vals['course_inter'] = [(6, 0, cids)]
            try:
                rid = call('leads.logic', 'create', vals,
                           context={'tracking_disable': True, 'otm_odoo19_sync': True})
            except Exception as e:  # noqa: BLE001
                raise UserError(_("Odoo 17 could not create the lead:\n%s") % str(e)[-600:])
            sent = lead._o17_push_children(call, rid, cache)
            action_note = _('created in Odoo 17 as lead #%(id)s (%(sent)s)') % {
                'id': rid, 'sent': ', '.join('%s %s' % (n, m.replace('lead.', '')) for m, n in sent.items()) or _('no history')}
        lead.with_context(otm_odoo17_sync_skip=True, tracking_disable=True).write({'odoo17_lead_id': rid})
        lead.message_post(body=_("Admission (Odoo 17): %s.") % action_note)
        return {
            'type': 'ir.actions.act_url',
            'url': '%s/web#id=%s&model=leads.logic&view_type=form' % (base, rid),
            'target': 'new',
        }
