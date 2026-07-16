from odoo import models, fields, api, _
from odoo.exceptions import UserError


class KanbanResponseWizard(models.TransientModel):
    """Quick call response + quality change from Kanban card."""
    _name = 'kanban.response.wizard'
    _description = 'Quick Response Wizard'

    lead_id         = fields.Many2one('leads.logic', required=True, readonly=True)
    lead_name       = fields.Char(related='lead_id.name', readonly=True)
    phone_number    = fields.Char(related='lead_id.phone_number', readonly=True)
    current_quality = fields.Selection(related='lead_id.lead_quality',
                                        string='Current Quality', readonly=True)

    # ── Lead Quality change ───────────────────────────────────────────────────
    new_quality = fields.Selection([
        ('new',                  '🆕  New'),
        ('first_attempt',        '🎯 First Attempt'),
        ('waiting_for_admission','⏳  Waiting for Admission'),
        ('admission',            '🎓  Admission'),
        ('hot',                  '🔥  Hot'),
        ('warm',                 '🌞  Warm'),
        ('cold',                 '❄️  Cold'),
        ('not_responding',       '🔕  Ringing Not Responding'),
        ('call_later',           '📞  Call Back'),
        ('follow_up',            '⏰  Follow Up'),
        ('not_reachable',        '⏳ Busy'),
        ('wrong_number',         '📵 Wrong number'),
        ('not_interested',       '❌ Not Interested'),
        ('not_attended',         '📵Not Attended'),
        ('already_joined',       '✅ Already Joined'),
    ], string='Lead Quality', required=True)

    # ── Response ──────────────────────────────────────────────────────────────
    response_text = fields.Text(
        string='Response',
        required=True,
        placeholder='Enter call response / notes...'
    )

    @api.onchange('lead_id')
    def _onchange_lead_id(self):
        if self.lead_id:
            self.new_quality = self.lead_id.lead_quality

    def action_save_response(self):
        self.ensure_one()
        lead = self.lead_id

        # Save quality if changed
        if self.new_quality and self.new_quality != lead.lead_quality:
            lead.write({'lead_quality': self.new_quality})

        # Save to call_response field (summary)
        lead.write({'call_response': self.response_text})

        # ── Create record in lead.response (Responses notebook tab) ──────────
        self.env['lead.response'].create({
            'lead_id': lead.id,
            'user_id': self.env.user.id,
            'comment': self.response_text,
            'response_time': fields.Datetime.now(),
            'is_editable': False,
        })

        # Also link to call.responses Many2many
        response_obj = self.env['call.responses'].search(
            [('name', '=', self.response_text)], limit=1
        )
        if not response_obj:
            response_obj = self.env['call.responses'].create(
                {'name': self.response_text}
            )
        lead.write({'call_responses': [(4, response_obj.id)]})

        # Post to chatter
        quality_label = dict(self._fields['new_quality'].selection).get(
            self.new_quality, self.new_quality)
        lead.message_post(
            body=(
                f"📞 <b>Response Logged</b><br/>"
                f"🏷️ Quality: <b>{quality_label}</b><br/>"
                f"💬 {self.response_text}"
            )
        )
        # Lead form is already open (JS navigated there before opening wizard)
        # Just close the dialog
        return {'type': 'ir.actions.act_window_close'}


class KanbanQualityWizard(models.TransientModel):
    """Quick lead quality change from Kanban card."""
    _name = 'kanban.quality.wizard'
    _description = 'Quick Lead Quality Wizard'

    lead_id = fields.Many2one('leads.logic', required=True, readonly=True)
    lead_name = fields.Char(related='lead_id.name', readonly=True)
    phone_number = fields.Char(related='lead_id.phone_number', readonly=True)
    current_quality = fields.Selection(related='lead_id.lead_quality',
                                        string='Current Quality', readonly=True)
    new_quality = fields.Selection([
        ('new',                  '🆕  New'),
        ('first_attempt',        '🎯 First Attempt'),
        ('waiting_for_admission','⏳  Waiting for Admission'),
        ('admission',            '🎓  Admission'),
        ('hot',                  '🔥  Hot'),
        ('warm',                 '🌞  Warm'),
        ('cold',                 '❄️  Cold'),
        ('not_responding',       '🔕  Ringing Not Responding'),
        ('call_later',           '📞  Call Back'),
        ('follow_up',            '⏰  Follow Up'),
        ('not_reachable',        '⏳ Busy'),
        ('wrong_number',         '📵 Wrong number'),
        ('not_interested',       '❌ Not Interested'),
        ('not_attended',         '📵Not Attended'),
        ('already_joined',       '✅ Already Joined'),
    ], string='Change To', required=True)
    reason = fields.Char(string='Reason (optional)')

    def action_update_quality(self):
        self.ensure_one()
        old = dict(self._fields['new_quality'].selection).get(
            self.lead_id.lead_quality, self.lead_id.lead_quality)
        new = dict(self._fields['new_quality'].selection).get(
            self.new_quality, self.new_quality)
        self.lead_id.write({'lead_quality': self.new_quality})
        msg = f"🏷️ <b>Lead Quality Changed</b>: {old} → {new}"
        if self.reason:
            msg += f"<br/>Reason: {self.reason}"
        self.lead_id.message_post(body=msg)
        return {'type': 'ir.actions.act_window_close'}


class CallRecordingUploadWizard(models.TransientModel):
    _name = 'call.recording.upload.wizard'
    _description = 'Upload Call Recording'

    call_log_id   = fields.Many2one('lead.call.log', required=True, readonly=True)
    recording     = fields.Binary(string='Recording File', required=True)
    recording_filename = fields.Char(string='Filename')

    def action_upload(self):
        self.ensure_one()
        import mimetypes
        mime = 'audio/mpeg'
        if self.recording_filename:
            guessed, _ = mimetypes.guess_type(self.recording_filename)
            if guessed:
                mime = guessed
        self.call_log_id.write({
            'recording': self.recording,
            'recording_filename': self.recording_filename,
            'recording_mimetype': mime,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '✅ Recording Uploaded',
                'message': f'Recording saved to call log.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
