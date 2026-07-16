# -*- coding: utf-8 -*-
"""XLSX export endpoint for the Call Report dashboard."""
import io
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class CallReportExportController(http.Controller):

    @http.route('/custom_leads/call_report/export', type='http',
                auth='user', methods=['GET'])
    def export_call_report(self, date_from=None, date_to=None, **kwargs):
        try:
            import xlsxwriter  # bundled with Odoo
        except ImportError:
            return request.make_response(
                "xlsxwriter not available on server",
                headers=[('Content-Type', 'text/plain')])

        CallLog = request.env['lead.call.log']
        data, rows = CallLog.get_call_report_export_rows(date_from, date_to)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Call Report')

        fmt_title = workbook.add_format({
            'bold': True, 'font_size': 14, 'font_color': '#1f2937'})
        fmt_sub = workbook.add_format({
            'font_size': 10, 'font_color': '#6b7280'})
        fmt_head = workbook.add_format({
            'bold': True, 'bg_color': '#4f46e5', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter'})
        fmt_cell = workbook.add_format({'border': 1})
        fmt_num = workbook.add_format({'border': 1, 'align': 'center'})
        fmt_tl = workbook.add_format({
            'border': 1, 'bold': True, 'bg_color': '#eef2ff'})
        fmt_tl_num = workbook.add_format({
            'border': 1, 'bold': True, 'bg_color': '#eef2ff',
            'align': 'center'})
        fmt_total = workbook.add_format({
            'border': 1, 'bold': True, 'bg_color': '#f3f4f6'})
        fmt_total_num = workbook.add_format({
            'border': 1, 'bold': True, 'bg_color': '#f3f4f6',
            'align': 'center'})

        sheet.write(0, 0, 'Call Report — Admission Officers & Team Leads',
                    fmt_title)
        sheet.write(1, 0, 'Period: %s  to  %s' % (
            data['date_from'], data['date_to']), fmt_sub)
        s = data['summary']
        sheet.write(2, 0, 'Total Calls: %s   |   Connected: %s   |   '
                          'Outgoing: %s   |   Incoming: %s   |   '
                          'Unique Leads: %s   |   Talk Time: %s' % (
                              s['total_calls'], s['connected'],
                              s['outgoing'], s['incoming'],
                              s['unique_leads'], s['total_duration']),
                    fmt_sub)

        headers = ['Team', 'Name', 'Role', 'Reporting TL', 'Total Calls',
                   'Outgoing', 'Incoming', 'Connected', 'Not Connected',
                   'Unique Leads', 'Talk Time', 'Avg Duration']
        header_row = 4
        for col, title in enumerate(headers):
            sheet.write(header_row, col, title, fmt_head)

        widths = [22, 26, 18, 22, 11, 10, 10, 11, 13, 12, 12, 12]
        for col, w in enumerate(widths):
            sheet.set_column(col, col, w)

        r = header_row + 1
        for row in rows:
            is_tl = row['role'] == 'Team Lead'
            f_txt = fmt_tl if is_tl else fmt_cell
            f_num = fmt_tl_num if is_tl else fmt_num
            sheet.write(r, 0, row['team'], f_txt)
            sheet.write(r, 1, row['name'], f_txt)
            sheet.write(r, 2, row['role'], f_txt)
            sheet.write(r, 3, row['tl_name'], f_txt)
            sheet.write(r, 4, row['calls'], f_num)
            sheet.write(r, 5, row['outgoing'], f_num)
            sheet.write(r, 6, row['incoming'], f_num)
            sheet.write(r, 7, row['connected'], f_num)
            sheet.write(r, 8, row['not_connected'], f_num)
            sheet.write(r, 9, row['unique_leads'], f_num)
            sheet.write(r, 10, row['duration'], f_num)
            sheet.write(r, 11, row['avg_duration'], f_num)
            r += 1

        # Totals row
        sheet.write(r, 0, 'TOTAL', fmt_total)
        sheet.write(r, 1, '', fmt_total)
        sheet.write(r, 2, '', fmt_total)
        sheet.write(r, 3, '', fmt_total)
        sheet.write(r, 4, sum(x['calls'] for x in rows), fmt_total_num)
        sheet.write(r, 5, sum(x['outgoing'] for x in rows), fmt_total_num)
        sheet.write(r, 6, sum(x['incoming'] for x in rows), fmt_total_num)
        sheet.write(r, 7, sum(x['connected'] for x in rows), fmt_total_num)
        sheet.write(r, 8, sum(x['not_connected'] for x in rows), fmt_total_num)
        sheet.write(r, 9, '', fmt_total)
        sheet.write(r, 10, s['total_duration'], fmt_total_num)
        sheet.write(r, 11, '', fmt_total)

        sheet.freeze_panes(header_row + 1, 0)
        workbook.close()
        output.seek(0)

        filename = 'call_report_%s_to_%s.xlsx' % (
            data['date_from'], data['date_to'])
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument.'
                 'spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename="%s"' % filename),
            ])
