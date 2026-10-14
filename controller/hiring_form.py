# -*- coding: utf-8 -*-
"""Public application form for a hiring lead. The link carries a private token, so only the applicant who
received it can open it. The details and the resume are saved on the lead."""
import base64
import html
import logging
import os

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)
MAX_BYTES = 5 * 1024 * 1024
EXTS = ('.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png')
FIELDS = [
    ('hiring_position', 'Position you are applying for', 'text'),
    ('hiring_qualification', 'Highest qualification', 'text'),
    ('hiring_experience', 'Total experience (years)', 'number'),
    ('hiring_current_company', 'Current or last company', 'text'),
    ('hiring_current_salary', 'Current salary per month', 'text'),
    ('hiring_expected_salary', 'Expected salary per month', 'text'),
    ('hiring_notice_period', 'When can you join', 'text'),
    ('hiring_email', 'Email', 'email'),
    ('hiring_skills', 'Skills and a few words about you', 'textarea'),
]
CSS = """body{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#f3f5f8;margin:0;color:#1f2933}
.w{max-width:560px;margin:0 auto;padding:20px 16px 40px}.c{background:#fff;border-radius:14px;padding:22px 20px;box-shadow:0 2px 12px rgba(0,0,0,.07)}
h1{font-size:20px;margin:0 0 4px}p.s{margin:0 0 16px;color:#52606d;font-size:14px}label{display:block;font-weight:600;font-size:14px;margin:14px 0 5px}
input,textarea{width:100%;box-sizing:border-box;border:1px solid #cbd2d9;border-radius:8px;padding:10px 11px;font-size:15px;font-family:inherit}
textarea{min-height:90px}button{margin-top:20px;width:100%;background:#1c3d6b;color:#fff;border:0;border-radius:10px;padding:13px;font-size:16px;font-weight:600}
.n{font-size:12px;color:#7b8794;margin-top:4px}.ok{color:#0e8f7e}.err{background:#fadbd6;color:#8a2a1d;padding:10px 12px;border-radius:8px;margin-bottom:12px;font-size:14px}"""


def _page(title, body):
    return request.make_response(
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title><style>%s</style></head><body><div class="w"><div class="c">%s</div></div></body></html>'
        % (html.escape(title), CSS, body), headers=[('Content-Type', 'text/html; charset=utf-8')])


class HiringFormController(http.Controller):

    def _lead(self, token):
        if not token or len(token) < 10:
            return request.env['leads.logic']
        return request.env['leads.logic'].sudo().search(
            [('hiring_form_token', '=', token), ('is_hiring', '=', True)], limit=1)

    def _form(self, lead, token, error=''):
        company = html.escape(request.env.company.sudo().name or '')
        rows = ''
        for fname, label, kind in FIELDS:
            val = lead[fname]
            val = '' if (val is False or val is None or (kind == 'number' and not val)) else val
            val = html.escape(str(val))
            if kind == 'textarea':
                rows += '<label>%s</label><textarea name="%s">%s</textarea>' % (label, fname, val)
            else:
                step = ' step="0.5" min="0"' if kind == 'number' else ''
                rows += '<label>%s</label><input type="%s" name="%s" value="%s"%s/>' % (label, kind, fname, val, step)
        resume_note = ('<div class="n ok">A resume is already uploaded (%s). Upload again only to replace it.</div>'
                       % html.escape(lead.hiring_resume_filename or '')) if lead.hiring_resume else ''
        body = (
            '<h1>Job application</h1><p class="s">%s. Hello %s, please fill in your details.</p>%s'
            '<form method="post" enctype="multipart/form-data" action="/hiring/apply/%s">'
            '<input type="hidden" name="csrf_token" value="%s"/>%s'
            '<label>Resume (PDF, Word or photo, up to 5 MB)</label><input type="file" name="resume" accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"/>%s'
            '<button type="submit">Submit application</button></form>'
            % (company, html.escape(lead.name or ''), ('<div class="err">%s</div>' % html.escape(error)) if error else '',
               html.escape(token), request.csrf_token(), rows, resume_note))
        return _page('Job application', body)

    @http.route('/hiring/apply/<string:token>', type='http', auth='public', methods=['GET'])
    def apply_get(self, token, **kw):
        lead = self._lead(token)
        if not lead:
            return _page('Link not valid', '<h1>Link not valid</h1><p class="s">This application link is not valid or has expired. Please ask the HR team for a new one.</p>')
        return self._form(lead, token)

    @http.route('/hiring/apply/<string:token>', type='http', auth='public', methods=['POST'])
    def apply_post(self, token, **post):
        lead = self._lead(token)
        if not lead:
            return _page('Link not valid', '<h1>Link not valid</h1><p class="s">This application link is not valid or has expired.</p>')
        vals = {}
        for fname, _label, kind in FIELDS:
            v = (post.get(fname) or '').strip()
            if kind == 'number':
                try:
                    v = float(v) if v else 0.0
                except ValueError:
                    return self._form(lead, token, 'Experience must be a number.')
            vals[fname] = v[:2000] if isinstance(v, str) else v
        f = post.get('resume')
        got_resume = False
        if f is not None and getattr(f, 'filename', ''):
            name = os.path.basename(f.filename)
            if not name.lower().endswith(EXTS):
                return self._form(lead, token, 'Please upload a PDF, Word or photo file.')
            data = f.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return self._form(lead, token, 'The resume is larger than 5 MB.')
            if data:
                vals.update({'hiring_resume': base64.b64encode(data), 'hiring_resume_filename': name[:120]})
                got_resume = True
        if not got_resume and not lead.hiring_resume:
            return self._form(lead, token, 'Please attach your resume.')
        vals['hiring_form_submitted_on'] = fields.Datetime.now()
        if lead.hiring_stage in ('new', 'resume_requested'):
            vals['hiring_stage'] = 'resume_received'
        try:
            lead.write(vals)
            owner = lead.lead_owner.user_id.partner_id
            lead.message_post(body='Application form submitted by %s%s.' % (lead.name, ' with resume' if got_resume else ''),
                              partner_ids=[owner.id] if owner else [], message_type='notification',
                              subtype_xmlid='mail.mt_comment')
        except Exception:  # noqa: BLE001
            _logger.exception('Hiring form save failed for lead %s', lead.id)
            return _page('Error', '<h1>Something went wrong</h1><p class="s">Please try again in a few minutes.</p>')
        return _page('Thank you', '<h1 class="ok">Thank you</h1><p class="s">Your application has been received. Our HR team will contact you soon.</p>')
