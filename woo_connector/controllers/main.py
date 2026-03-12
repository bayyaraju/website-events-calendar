# -*- coding: utf-8 -*-
import json
import logging

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class WooWebhookController(http.Controller):
    """
    Receives real-time webhook POSTs from WooCommerce.

    WooCommerce sends plain JSON (application/json) via HTTP POST — NOT JSON-RPC.
    All routes must use type='http' so Odoo does not try to parse the body as
    a JSON-RPC envelope (which would silently discard the payload).
    """

    @http.route('/woo/webhook/order', type='http', auth='public', methods=['POST'], csrf=False)
    def receive_order(self, **kwargs):
        """Receive order created/updated/deleted webhooks from WooCommerce."""
        return self._handle_webhook('order')

    @http.route('/woo/webhook/product', type='http', auth='public', methods=['POST'], csrf=False)
    def receive_product(self, **kwargs):
        """Receive product created/updated/deleted webhooks from WooCommerce."""
        return self._handle_webhook('product')

    @http.route('/woo/webhook/customer', type='http', auth='public', methods=['POST'], csrf=False)
    def receive_customer(self, **kwargs):
        """Receive customer created/updated webhooks from WooCommerce."""
        return self._handle_webhook('customer')

    @http.route('/woo/webhook/refund', type='http', auth='public', methods=['POST'], csrf=False)
    def receive_refund(self, **kwargs):
        """Receive order refunded webhooks from WooCommerce."""
        return self._handle_webhook('refund')

    @http.route('/woo/webhook/stock', type='http', auth='public', methods=['POST'], csrf=False)
    def receive_stock(self, **kwargs):
        """Receive product.updated webhooks used for stock change notifications."""
        return self._handle_webhook('stock')

    # ── Internal helpers ────────────────────────────────────────────────

    def _handle_webhook(self, webhook_type):
        """
        Parse, validate and enqueue an incoming WooCommerce webhook.

        WooCommerce sends:
          Content-Type: application/json
          X-WC-Webhook-Source: https://yourstore.com/
          X-WC-Webhook-Signature: <base64 HMAC-SHA256>
          Body: raw JSON payload
        """
        try:
            # ── 1. Read raw body BEFORE anything else ───────────────────
            #   request.httprequest.data is the raw bytes; safe to call multiple times.
            raw_body = request.httprequest.data
            if not raw_body:
                _logger.warning(f'[WooWebhook] Empty body received for type={webhook_type}')
                return Response('Empty payload', status=400)

            # ── 2. Parse JSON ────────────────────────────────────────────
            try:
                data = json.loads(raw_body.decode('utf-8'))
            except (ValueError, UnicodeDecodeError) as parse_err:
                _logger.warning(f'[WooWebhook] JSON parse error: {parse_err}')
                return Response('Invalid JSON', status=400)

            # ── 3. Identify WooCommerce instance from Source header ──────
            source = request.httprequest.headers.get('X-WC-Webhook-Source', '')
            signature = request.httprequest.headers.get('X-WC-Webhook-Signature', '')
            topic = request.httprequest.headers.get('X-WC-Webhook-Topic', '')

            instance = self._find_instance(source)
            if not instance:
                _logger.warning(f'[WooWebhook] No instance for source="{source}", trying fallback')
                instance = request.env['woo.instance'].sudo().search(
                    [('active', '=', True), ('state', '=', 'connected')], limit=1
                )
            if not instance:
                _logger.error('[WooWebhook] No active connected WooCommerce instance found')
                return Response('No active instance', status=404)

            # ── 4. Validate HMAC signature (if secret configured) ────────
            if instance.webhook_secret and signature:
                if not instance.validate_webhook_signature(raw_body, signature):
                    _logger.warning(
                        f'[WooWebhook] Invalid signature for instance "{instance.name}"'
                    )
                    return Response('Invalid signature', status=401)

            # ── 5. Enqueue for async processing ─────────────────────────
            self._enqueue(instance, webhook_type, topic, data)

            _logger.info(
                f'[WooWebhook] Queued {webhook_type} #{data.get("id", "?")} '
                f'from {source} (topic={topic})'
            )
            # WooCommerce expects a 200 response to confirm receipt
            return Response(
                json.dumps({'status': 'success', 'queued': True}),
                status=200,
                content_type='application/json',
            )

        except Exception as e:
            _logger.exception(f'[WooWebhook] Unhandled error in {webhook_type} handler: {e}')
            # Still return 200 so WooCommerce does not keep retrying a broken payload
            return Response(
                json.dumps({'status': 'error', 'message': str(e)}),
                status=200,
                content_type='application/json',
            )

    def _find_instance(self, source_url):
        """Find a WooCommerce instance whose store_url matches the webhook source header."""
        if not source_url:
            return None
        source_clean = source_url.rstrip('/')
        for inst in request.env['woo.instance'].sudo().search([('active', '=', True)]):
            if inst.store_url and inst.store_url.rstrip('/') in source_clean:
                return inst
        return None

    def _enqueue(self, instance, queue_type, topic, data):
        """Create a woo.queue.line record for async processing."""
        woo_id = data.get('id', 0)
        request.env['woo.queue.line'].sudo().create({
            'instance_id': instance.id,
            'queue_type': queue_type,
            'name': f'{queue_type.capitalize()} #{woo_id} ({topic})',
            'woo_id': woo_id,
            'data': json.dumps(data),
            'state': 'draft',
        })
