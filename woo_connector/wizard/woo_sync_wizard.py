# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class WooSyncWizard(models.TransientModel):
    _name = 'woo.sync.wizard'
    _description = 'WooCommerce Sync Wizard'

    instance_id = fields.Many2one('woo.instance', string='Instance', required=True)
    sync_type = fields.Selection([
        ('products', 'Products'),
        ('categories', 'Product Categories'),
        ('product_images', 'Product Images'),
        ('stock', 'Stock / Inventory'),
        ('orders', 'Orders'),
        ('customers', 'Customers'),
        ('coupons', 'Coupons'),
        ('all', 'All (Full Sync)'),
    ], string='Sync Type', required=True, default='products')
    date_from = fields.Datetime(string='From Date')
    date_to = fields.Datetime(string='To Date')

    def action_sync(self):
        self.ensure_one()
        instance = self.instance_id

        if instance.state != 'connected':
            raise UserError(_('Please test connection first.'))

        results = []

        def do(fn, label):
            try:
                fn(instance)
                results.append(f'✓ {label}')
            except Exception as e:
                results.append(f'✗ {label}: {str(e)}')

        sync_type = self.sync_type

        if sync_type in ('categories', 'all'):
            do(self.env['woo.product.category'].sync_categories_from_woo, 'Product Categories')

        if sync_type in ('products', 'all'):
            do(self.env['woo.product.template'].sync_products, 'Products')

        if sync_type in ('product_images', 'all'):
            do(self._sync_product_images, 'Product Images')

        if sync_type in ('stock', 'all'):
            do(self.env['woo.product.template'].sync_stock_to_woo, 'Stock / Inventory')

        if sync_type in ('orders', 'all'):
            do(self.env['sale.order'].import_orders_from_woo, 'Orders')

        if sync_type in ('customers', 'all'):
            do(self.env['res.partner'].import_customers_from_woo, 'Customers')

        if sync_type in ('coupons', 'all'):
            do(self.env['woo.coupon'].import_coupons_from_woo, 'Coupons')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': '\n'.join(results) + '\n\nCheck Monitoring → Sync Logs for details.',
                'type': 'success' if all('✓' in r for r in results) else 'warning',
                'sticky': True,
            }
        }

    def _sync_product_images(self, instance):
        """Re-download and update product images from WooCommerce."""
        import base64
        import requests

        mappings = self.env['woo.product.template'].search([
            ('instance_id', '=', instance.id),
            ('woo_id', '!=', False),
            ('product_tmpl_id', '!=', False),
        ])
        instance._log('info', f'Syncing images for {len(mappings)} products')
        synced = 0
        for mapping in mappings:
            if not mapping.woo_image_url:
                continue
            try:
                resp = requests.get(mapping.woo_image_url, timeout=15)
                if resp.status_code == 200:
                    mapping.product_tmpl_id.image_1920 = base64.b64encode(resp.content)
                    synced += 1
            except Exception as e:
                instance._log('warning', f'Image sync failed for {mapping.name}: {str(e)}')
        instance._log('info', f'Product image sync complete: {synced} images updated')
