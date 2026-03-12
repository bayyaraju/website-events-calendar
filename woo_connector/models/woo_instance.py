# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging
import requests
from datetime import datetime, timedelta
from requests.auth import HTTPBasicAuth

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

WOOCOMMERCE_API_VERSION = 'wc/v3'


class WooInstance(models.Model):
    _name = 'woo.instance'
    _description = 'WooCommerce Instance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    # ─── Basic Config ─────────────────────────────────────────────────
    name = fields.Char(string='Instance Name', required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('connected', 'Connected'),
        ('error', 'Error'),
    ], default='draft', tracking=True)

    # ─── Connection ───────────────────────────────────────────────────
    store_url = fields.Char(string='Store URL', required=True,
                            help='e.g. https://yourstore.com')
    consumer_key = fields.Char(string='Consumer Key', required=True)
    consumer_secret = fields.Char(string='Consumer Secret', required=True)
    webhook_secret = fields.Char(string='Webhook Secret',
                                  help='Used to validate incoming webhooks from WooCommerce')

    # ─── Sync Config ──────────────────────────────────────────────────
    company_id = fields.Many2one('res.company', string='Company',
                                  default=lambda self: self.env.company)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist')
    lang_id = fields.Many2one('res.lang', string='Language')
    default_product_type = fields.Selection([
        ('product', 'Storable Product'),
        ('consu', 'Consumable'),
        ('service', 'Service'),
    ], default='product', string='Default Product Type',
       help='Maps to detailed_type on product.template (Odoo 17+)')

    # ─── Order Config ─────────────────────────────────────────────────
    auto_confirm_order = fields.Boolean(string='Auto Confirm Orders', default=True)
    auto_create_invoice = fields.Boolean(string='Auto Create Invoice', default=False)
    auto_validate_invoice = fields.Boolean(string='Auto Validate Invoice', default=False)
    order_prefix = fields.Char(string='Order Prefix', default='WOO-')
    import_order_status_ids = fields.Many2many(
        'woo.order.status', string='Import Order Statuses',
        help='Only import orders with these statuses from WooCommerce'
    )

    # ─── Product Config ────────────────────────────────────────────────
    sync_images = fields.Boolean(string='Sync Product Images', default=True)
    sync_stock = fields.Boolean(string='Sync Stock', default=True)
    sync_price = fields.Boolean(string='Sync Price', default=True)
    create_products_in_odoo = fields.Boolean(
        string='Create Products in Odoo', default=True,
        help='Automatically create Odoo products for WooCommerce products not yet mapped'
    )

    # ─── Tax Config ────────────────────────────────────────────────────
    tax_mapping_ids = fields.One2many('woo.tax', 'instance_id', string='Tax Mappings')

    # ─── Shipping Config ───────────────────────────────────────────────
    shipping_mapping_ids = fields.One2many(
        'woo.shipping.method', 'instance_id', string='Shipping Methods'
    )

    # ─── Analytics ─────────────────────────────────────────────────────
    total_orders_synced = fields.Integer(string='Orders Synced', compute='_compute_stats')
    total_products_synced = fields.Integer(string='Products Synced', compute='_compute_stats')
    total_coupons_synced = fields.Integer(string='Coupons Synced', compute='_compute_stats')
    total_customers_synced = fields.Integer(string='Customers Synced', compute='_compute_stats')
    last_order_sync = fields.Datetime(string='Last Order Sync', readonly=True)
    last_product_sync = fields.Datetime(string='Last Product Sync', readonly=True)
    last_stock_sync = fields.Datetime(string='Last Stock Sync', readonly=True)

    # ─── Cron Config ───────────────────────────────────────────────────
    order_sync_interval = fields.Integer(string='Order Sync Interval (min)', default=15)
    product_sync_interval = fields.Integer(string='Product Sync Interval (min)', default=60)
    stock_sync_interval = fields.Integer(string='Stock Sync Interval (min)', default=30)

    # ─── Log / Queue ────────────────────────────────────────────────────
    log_ids = fields.One2many('woo.log', 'instance_id', string='Logs')
    queue_line_ids = fields.One2many('woo.queue.line', 'instance_id', string='Queue')
    log_count = fields.Integer(string='Logs', compute='_compute_log_count')
    queue_count = fields.Integer(string='Queue Items', compute='_compute_queue_count')
    failed_queue_count = fields.Integer(string='Failed', compute='_compute_queue_count')

    @api.depends('log_ids')
    def _compute_log_count(self):
        for rec in self:
            rec.log_count = len(rec.log_ids)

    @api.depends('queue_line_ids')
    def _compute_queue_count(self):
        for rec in self:
            rec.queue_count = len(rec.queue_line_ids)
            rec.failed_queue_count = len(rec.queue_line_ids.filtered(
                lambda q: q.state == 'failed'
            ))

    @api.depends()
    def _compute_stats(self):
        for rec in self:
            rec.total_orders_synced = self.env['sale.order'].search_count([
                ('woo_instance_id', '=', rec.id)
            ])
            rec.total_products_synced = self.env['woo.product.template'].search_count([
                ('instance_id', '=', rec.id)
            ])
            rec.total_coupons_synced = self.env['woo.coupon'].search_count([
                ('instance_id', '=', rec.id)
            ])
            rec.total_customers_synced = self.env['res.partner'].search_count([
                ('woo_instance_id', '=', rec.id)
            ])

    # ─── API Helpers ────────────────────────────────────────────────────
    def _get_api_url(self, endpoint):
        """Build full WooCommerce REST API URL."""
        base = self.store_url.rstrip('/')
        return f"{base}/wp-json/{WOOCOMMERCE_API_VERSION}/{endpoint}"

    def _get_auth(self):
        return HTTPBasicAuth(self.consumer_key, self.consumer_secret)

    def _api_call(self, method, endpoint, data=None, params=None):
        """Generic WooCommerce API call with error handling and logging."""
        url = self._get_api_url(endpoint)
        _logger.debug(f'[WooConnector] API {method} {url} data={data}')
        try:
            response = requests.request(
                method,
                url,
                auth=self._get_auth(),
                json=data,
                params=params or {},
                timeout=30,
            )
            _logger.debug(f'[WooConnector] API response {response.status_code}: {response.text[:200]}')
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            self._log('error', f'Timeout on {method} {endpoint}')
            raise UserError(_('WooCommerce API Timeout. Please try again.'))
        except requests.exceptions.ConnectionError:
            self._log('error', f'Connection error on {method} {endpoint}')
            raise UserError(_('Cannot connect to WooCommerce. Check store URL.'))
        except requests.exceptions.HTTPError as e:
            error_msg = str(e)
            try:
                error_msg = response.json().get('message', error_msg)
            except Exception:
                pass
            self._log('error', f'HTTP error on {method} {endpoint}: {error_msg}')
            raise UserError(_(f'WooCommerce API Error: {error_msg}'))

    def _api_get(self, endpoint, params=None):
        return self._api_call('GET', endpoint, params=params)

    def _api_post(self, endpoint, data):
        return self._api_call('POST', endpoint, data=data)

    def _api_put(self, endpoint, data):
        return self._api_call('PUT', endpoint, data=data)

    def _api_delete(self, endpoint):
        return self._api_call('DELETE', endpoint)

    def _api_get_all(self, endpoint, params=None):
        """Paginate through all results from a WooCommerce endpoint."""
        # Copy params to avoid mutating the caller's dict
        page_params = dict(params or {})
        page_params['per_page'] = 100
        page = 1
        results = []
        while True:
            page_params['page'] = page
            data = self._api_get(endpoint, params=page_params)
            if not data:
                break
            results.extend(data)
            if len(data) < 100:
                break
            page += 1
        return results

    # ─── Actions ────────────────────────────────────────────────────────
    def action_test_connection(self):
        """Test connection to WooCommerce store."""
        self.ensure_one()
        try:
            result = self._api_get('system_status')
            if result:
                self.state = 'connected'
                self._log('info', 'Connection test successful')
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Successful'),
                        'message': _('Successfully connected to WooCommerce store!'),
                        'type': 'success',
                    }
                }
        except Exception as e:
            self.state = 'error'
            raise UserError(str(e))

    def action_sync_orders(self):
        """Import orders from WooCommerce."""
        self.ensure_one()
        self.env['sale.order'].sudo().import_orders_from_woo(self)

    def action_sync_products(self):
        """Sync products bidirectionally."""
        self.ensure_one()
        self.env['woo.product.template'].sudo().sync_products(self)

    def action_sync_stock(self):
        """Push stock to WooCommerce."""
        # self.ensure_one()
        self.env['woo.product.template'].sudo().sync_stock_to_woo(self)

    def action_sync_customers(self):
        """Import customers from WooCommerce."""
        self.ensure_one()
        self.env['res.partner'].sudo().import_customers_from_woo(self)

    def action_sync_coupons(self):
        """Import coupons from WooCommerce."""
        self.ensure_one()
        self.env['woo.coupon'].sudo().import_coupons_from_woo(self)

    def action_sync_product_images(self):
        """Re-download and update product images from WooCommerce."""
        self.ensure_one()
        import base64
        import requests as req
        mappings = self.env['woo.product.template'].search([
            ('instance_id', '=', self.id),
            ('woo_id', '!=', False),
            ('woo_image_url', '!=', False),
        ])
        self._log('info', f'Syncing images for {len(mappings)} products')
        synced = 0
        for mapping in mappings:
            try:
                resp = req.get(mapping.woo_image_url, timeout=15)
                if resp.status_code == 200:
                    img_data = base64.b64encode(resp.content)
                    # Store on woo.product.template record
                    mapping.woo_image = img_data
                    # Also update the linked Odoo product if present
                    if mapping.product_tmpl_id:
                        mapping.product_tmpl_id.image_1920 = img_data
                    synced += 1
            except Exception as e:
                self._log('warning', f'Image sync failed for {mapping.name}: {str(e)}')
        self._log('info', f'Product image sync complete: {synced} images updated')

    def action_view_products(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('WooCommerce Products'),
            'res_model': 'woo.product.template',
            'domain': [('instance_id', '=', self.id)],
            'view_mode': 'list,form',
        }

    def action_view_orders(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('WooCommerce Orders'),
            'res_model': 'woo.sale.order',
            'domain': [('instance_id', '=', self.id)],
            'view_mode': 'list,form',
        }

    def action_view_coupons(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('WooCommerce Coupons'),
            'res_model': 'woo.coupon',
            'domain': [('instance_id', '=', self.id)],
            'view_mode': 'list,form',
        }

    def action_view_customers(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('WooCommerce Customers'),
            'res_model': 'res.partner',
            'domain': [('woo_instance_id', '=', self.id), ('is_woo_customer', '=', True)],
            'view_mode': 'list,form',
        }

    def action_view_logs(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Logs'),
            'res_model': 'woo.log',
            'domain': [('instance_id', '=', self.id)],
            'view_mode': 'list,form',
        }

    def action_view_queue(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Queue'),
            'res_model': 'woo.queue.line',
            'domain': [('instance_id', '=', self.id)],
            'view_mode': 'list,form',
        }

    def action_retry_failed(self):
        """Retry all failed queue items."""
        failed = self.queue_line_ids.filtered(lambda q: q.state == 'failed')
        for line in failed:
            line.action_process()

    # ─── Webhook Validation ─────────────────────────────────────────────
    def validate_webhook_signature(self, payload_body, signature):
        """HMAC-SHA256 validation of WooCommerce webhook."""
        if not self.webhook_secret:
            return True  # No secret configured, allow all
        computed = hmac.new(
            self.webhook_secret.encode('utf-8'),
            payload_body,
            hashlib.sha256
        ).digest()
        import base64
        computed_b64 = base64.b64encode(computed).decode('utf-8')
        return hmac.compare_digest(computed_b64, signature)

    # ─── Logging ────────────────────────────────────────────────────────
    def _log(self, level, message, model=None, res_id=None):
        self.env['woo.log'].sudo().create({
            'instance_id': self.id,
            'level': level,
            'message': message,
            'model': model or '',
            'res_id': res_id or 0,
        })
        log_func = getattr(_logger, level, _logger.info)
        log_func(f'[WooConnector][{self.name}] {message}')

    # ─── Cron Methods ────────────────────────────────────────────────────
    @api.model
    def cron_sync_orders(self):
        instances = self.search([('active', '=', True), ('state', '=', 'connected')])
        for instance in instances:
            try:
                instance.action_sync_orders()
            except Exception as e:
                instance._log('error', f'Cron order sync failed: {str(e)}')

    @api.model
    def cron_sync_products(self):
        instances = self.search([('active', '=', True), ('state', '=', 'connected')])
        for instance in instances:
            try:
                instance.action_sync_products()
            except Exception as e:
                instance._log('error', f'Cron product sync failed: {str(e)}')

    @api.model
    def cron_sync_stock(self):
        instances = self.search([('active', '=', True), ('state', '=', 'connected')])
        for instance in instances:
            try:
                instance.action_sync_stock()
            except Exception as e:
                instance._log('error', f'Cron stock sync failed: {str(e)}')

    @api.model
    def cron_sync_coupons(self):
        instances = self.search([('active', '=', True), ('state', '=', 'connected')])
        for instance in instances:
            try:
                instance.action_sync_coupons()
            except Exception as e:
                instance._log('error', f'Cron coupon sync failed: {str(e)}')

    @api.model
    def cron_sync_customers(self):
        instances = self.search([('active', '=', True), ('state', '=', 'connected')])
        for instance in instances:
            try:
                instance.action_sync_customers()
            except Exception as e:
                instance._log('error', f'Cron customer sync failed: {str(e)}')

    @api.model
    def cron_process_queue(self):
        """Process pending queue items."""
        pending = self.env['woo.queue.line'].search([
            ('state', 'in', ['draft', 'failed']),
            ('retry_count', '<', 5),
        ], limit=50)
        for line in pending:
            line.action_process()


class WooOrderStatus(models.Model):
    _name = 'woo.order.status'
    _description = 'WooCommerce Order Status'

    name = fields.Char(required=True)
    code = fields.Char(required=True)