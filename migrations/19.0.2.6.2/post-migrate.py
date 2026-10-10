# Repair chatter messages imported from Odoo 17 that show raw tags ("<b>New Re-Enquiry</b> ... &nbsp;").
import html
import logging
import re

_logger = logging.getLogger(__name__)
_TAG = re.compile(r'&lt;/?(b|br|strong|i|em|u|p|div|span|ul|ol|li|a)\b', re.I)


def migrate(cr, version):
    cr.execute("""
        SELECT id, body FROM mail_message
         WHERE model = 'leads.logic' AND body ~* '&lt;/?(b|br|strong|i|em|u|p|div|span|ul|ol|li|a)\\y'
    """)
    rows = cr.fetchall()
    fixed = 0
    for mid, body in rows:
        if body and _TAG.search(body):
            cr.execute("UPDATE mail_message SET body = %s WHERE id = %s", (html.unescape(body), mid))
            fixed += 1
    _logger.info("custom_leads_19: repaired %s chatter messages with escaped HTML", fixed)
