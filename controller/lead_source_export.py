# -*- coding: utf-8 -*-
"""XLSX export endpoint for the Leads list view, naming the downloaded file
after the selected leads' Source instead of the generic default filename.

If every selected lead shares one Source, the file is named after that
Source (sanitized for filesystem safety). If leads from multiple different
Sources are selected together, it falls back to
'Leads_Multiple_Sources_<date>.xlsx' since there's no single source name to
use.
"""
import io
import logging
import re

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Fields exported, in order. Adjust this list to change what columns appear
# in the download — it mirrors the columns visible on the Leads list view.
EXPORT_FIELDS = [
    ('reference_no', 'Reference'),
    ('name', 'Lead Name'),
    ('phone_number', 'Mobile'),
    ('phone_number_second', 'Second Phone'),
    ('parent_number', 'Parent Number'),
    ('email_address', 'Email'),
    ('place', 'Place'),
    ('district', 'District'),
    ('country', 'Country'),
    ('college_name', 'College / School'),
    ('academic_year', 'Academic Year'),
    ('course_interested', 'Course Interested'),
    ('course_inter', 'Course Interested In'),
    ('preferred_course', 'Preferred Course'),
    ('mode_of_study', 'Mode of Study'),
    ('source_name', 'Leads Source'),
    ('source_campaign_id', 'Source Campaign'),
    ('lead_quality', 'Lead Quality'),
    ('lead_stage_category', 'Stage'),
    ('state', 'State'),
    ('lead_owner', 'Lead Owner'),
    ('team_id', 'Team'),
    ('tele_caller_id', 'Tele Caller'),
    ('create_date', 'Created On'),
    ('assigned_date', 'Assigned Date'),
    ('reassign_date', 'Reassign Date'),
    ('auto_reassign_count', 'Auto Reassignments'),
    ('first_called_dt', 'First Called On'),
    ('call_count', 'Calls'),
    ('total_call_duration', 'Total Call Duration'),
    ('next_follow_up_date', 'Next Follow Up'),
    ('third_response', 'Last Response'),
    ('remarks', 'Remarks'),
    ('lost_reason', 'Lost Reason'),
    ('admission_status', 'Admission'),
    ('admission_date', 'Admission Date'),
    ('admission_course', 'Admission Course'),
    ('admission_batch', 'Admission Batch'),
    ('batch_fee', 'Expected Revenue'),
    ('booking_amount', 'Booking Amount'),
    ('admission_amount', 'Admission Fee'),
    ('receipt_no', 'Receipt No'),
    ('is_abroad', 'Abroad Lead'),
]


def _cell(lead, fname):
    """Readable value for any field type (selection label, names for relations, local time for datetimes)."""
    field = lead._fields.get(fname)
    if field is None:
        return getattr(lead, fname, '') if hasattr(lead, fname) else ''
    value = lead[fname]
    if value is False or value is None:
        return 0 if field.type in ('integer', 'float') else ''
    t = field.type
    if t == 'selection':
        sel = field._description_selection(lead.env)
        return dict(sel).get(value, value)
    if t in ('many2one',):
        return value.display_name or ''
    if t in ('many2many', 'one2many'):
        return ', '.join(value.mapped('display_name'))
    if t == 'datetime':
        try:
            return fields.Datetime.context_timestamp(lead, value).strftime('%d-%m-%Y %H:%M')
        except Exception:  # noqa: BLE001
            return str(value)
    if t == 'date':
        return value.strftime('%d-%m-%Y')
    if t == 'boolean':
        return 'Yes' if value else 'No'
    return value


_SKIP_PREFIX = ('message_', 'activity_', 'my_activity', 'website_message', 'rating_')
_SKIP_NAMES = {'id', 'display_name', 'write_uid', 'write_date', '__last_update', 'has_message', 'access_url',
               'access_token', 'access_warning'}


def _all_columns(Lead):
    """The curated columns first (in their order), then EVERY other stored field of the lead model,
    so the export carries all the data. One2many fields (call logs, history ...) and binary / html fields are left out."""
    cols = [(f, l) for f, l in EXPORT_FIELDS if f in Lead._fields]
    seen = {f for f, _l in cols}
    extra = []
    for fname, field in Lead._fields.items():
        if (fname in seen or fname in _SKIP_NAMES or fname.startswith(_SKIP_PREFIX)
                or not field.store or field.type in ('one2many', 'binary', 'html', 'properties', 'json')):
            continue
        extra.append((fname, field.string or fname))
    extra.sort(key=lambda x: x[1].lower())
    return cols + extra


def _safe_filename(name):
    """Strip characters that are unsafe in a downloaded filename, keep it
    readable."""
    name = re.sub(r'[\\/*?:"<>|]', '', name or '')
    name = name.strip().replace(' ', '_')
    return name or 'Leads_Export'


class LeadSourceExportController(http.Controller):

    @http.route('/custom_leads/export_by_source', type='http',
                auth='user', methods=['GET'])
    def export_by_source(self, ids=None, **kwargs):
        try:
            import xlsxwriter
        except ImportError:
            return request.make_response(
                "xlsxwriter not available on server",
                headers=[('Content-Type', 'text/plain')])

        if not ids:
            return request.make_response(
                "No lead ids provided",
                headers=[('Content-Type', 'text/plain')])

        try:
            id_list = [int(i) for i in ids.split(',') if i.strip()]
        except ValueError:
            return request.make_response(
                "Invalid ids parameter",
                headers=[('Content-Type', 'text/plain')])

        Lead = request.env['leads.logic']
        if not Lead._user_can_export():
            return request.make_response(
                "Exporting leads is allowed only for Admin, Manager and Team Lead.",
                headers=[('Content-Type', 'text/plain')], status=403)
        leads = Lead.with_context(tz=request.env.user.tz or 'Asia/Kolkata').browse(id_list).exists()
        if not leads:
            return request.make_response(
                "No matching leads found",
                headers=[('Content-Type', 'text/plain')])

        source_names = set(leads.mapped('source_name'))
        source_names.discard(False)
        source_names.discard('')
        if len(source_names) == 1:
            base_name = _safe_filename(next(iter(source_names)))
        else:
            import datetime
            base_name = 'Leads_Multiple_Sources_%s' % datetime.date.today()
        filename = '%s.xlsx' % base_name

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Leads')

        fmt_head = workbook.add_format({
            'bold': True, 'bg_color': '#4f46e5', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter'})
        fmt_cell = workbook.add_format({'border': 1})

        cols = _all_columns(Lead)
        for col, (_f, label) in enumerate(cols):
            sheet.write(0, col, label, fmt_head)
            sheet.set_column(col, col, max(14, min(40, len(label) + 6)))

        r = 1
        for lead in leads:
            for col, (fname, _l) in enumerate(cols):
                value = _cell(lead, fname)
                sheet.write(r, col, value if value is not False else '',
                            fmt_cell)
            r += 1

        sheet.freeze_panes(1, 0)
        workbook.close()
        output.seek(0)

        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument.'
                 'spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename="%s"' % filename),
            ])
