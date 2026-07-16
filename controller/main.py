import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class LeadsController(http.Controller):

    @http.route('/leads/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def leads_webhook(self, **kwargs):
        """Generic webhook endpoint for incoming lead data."""
        try:
            data = json.loads(request.httprequest.data)
            _logger.info("Leads webhook received: %s", data)
            return {'status': 'ok'}
        except Exception as e:
            _logger.error("Leads webhook error: %s", str(e))
            return {'status': 'error', 'message': str(e)}
