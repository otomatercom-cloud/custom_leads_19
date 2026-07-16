# -*- coding: utf-8 -*-
"""Bulk approval for Re-Attempt requests (list view multi-select)."""
import logging

from odoo import _, models

_logger = logging.getLogger(__name__)


class LeadReattemptBulk(models.Model):
    _inherit = "otomater.lead.reattempt"

    def action_bulk_approve(self):
        """Approve every selected request that is in Pending Review.

        Unlike calling action_approve on a mixed selection (which raises on
        the first non-pending record and aborts everything), this:
          * silently skips records that are not pending_review,
          * wraps EACH approval in its own savepoint, so one bad record
            (e.g. a validation error while writing its lead) doesn't roll
            back the approvals already done in this batch,
          * finishes with a summary notification.
        """
        pending = self.filtered(lambda r: r.review_status == 'pending_review')
        skipped = len(self) - len(pending)

        approved, failed = 0, []
        for rec in pending:
            try:
                with self.env.cr.savepoint():
                    rec.action_approve()
                approved += 1
            except Exception as e:
                _logger.warning(
                    "Bulk approve: re-attempt %s (id %s) failed: %s",
                    rec.name, rec.id, e)
                failed.append("%s (%s)" % (rec.name, str(e)[:80]))

        parts = [_("Approved: %s") % approved]
        if skipped:
            parts.append(_("Skipped (not Pending Review): %s") % skipped)
        if failed:
            parts.append(_("Failed: %s — %s") % (
                len(failed), '; '.join(failed[:5])))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bulk Approve — Re-Attempts'),
                'message': '\n'.join(parts),
                'type': 'danger' if failed
                        else ('warning' if skipped else 'success'),
                'sticky': bool(failed),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
