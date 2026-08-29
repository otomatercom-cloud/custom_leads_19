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

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Fields exported, in order. Adjust this list to change what columns appear
# in the download — it mirrors the columns visible on the Leads list view.
EXPORT_FIELDS = [
    ('reference_no', 'Reference'),
    ('name', 'Lead Name'),
    ('mobile', 'Mobile'),
    ('course_interested', 'Course Interested'),
    ('source_name', 'Leads Source'),
    ('lead_quality', 'Lead Quality'),
    ('state', 'State'),
    ('lead_owner', 'Lead Owner'),
]


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
        leads = Lead.browse(id_list).exists()
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

        for col, (_, label) in enumerate(EXPORT_FIELDS):
            sheet.write(0, col, label, fmt_head)
        widths = [16, 22, 14, 22, 22, 16, 14, 18]
        for col, w in enumerate(widths):
            sheet.set_column(col, col, w)

        r = 1
        for lead in leads:
            for col, (fname, _) in enumerate(EXPORT_FIELDS):
                value = getattr(lead, fname, '')
                if hasattr(value, 'display_name'):
                    value = value.display_name
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
