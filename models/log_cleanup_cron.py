# -*- coding: utf-8 -*-
# OPL-1
from odoo import models, fields


class LeadsLogic(models.Model):
    """Extends leads.logic with a scheduled cleanup for its own tracked-field
    notification history. Deliberately scoped ONLY to message_type =
    'notification' (system-generated field-change/tracking messages) — never
    touches 'comment' (chatter notes/emails), which is real business
    correspondence and must never be auto-deleted.

    Background: a bug in urbanchat_gsheet_connector's sync (fixed
    separately) caused ~2.9M notification messages to accumulate on
    leads.logic in under two months, growing mail_message to 5GB+ and
    causing delete/backup slowness across the whole database. This cron is
    the ongoing safety net so any future misbehaving process can never
    silently repeat that — old notification spam self-heals within 3 days
    instead of accumulating for weeks. See erp-tooling.md finding #45.
    """
    _inherit = 'leads.logic'

    def _cron_purge_old_notifications(self, days=3, batch_size=5000):
        """Delete notification-type mail.message rows for leads.logic older
        than `days`, in small batches so this never risks a MemoryError on
        a large backlog (the exact failure mode that started this
        investigation). Runs daily via ir.cron — see
        data/log_cleanup_cron.xml."""
        Message = self.env['mail.message'].sudo()
        from datetime import timedelta
        cutoff = fields.Datetime.now() - timedelta(days=days)

        total_deleted = 0
        while True:
            stale = Message.search([
                ('model', '=', 'leads.logic'),
                ('message_type', '=', 'notification'),
                ('create_date', '<', cutoff),
            ], limit=batch_size)
            if not stale:
                break
            count = len(stale)
            stale.unlink()
            total_deleted += count
            if count < batch_size:
                break
        return total_deleted
