# -*- coding: utf-8 -*-
import base64
import logging
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WooProductTemplate(models.Model):
    _name = 'woo.product.template'
    _description = 'WooCommerce Product'
    _inherit = ['mail.thread', 'woo.mixin']
    _rec_name = 'name'

    name = fields.Char(string='WooCommerce Product Name', required=True)
    instance_id = fields.Many2one('woo.instance', string='Instance', required=True, ondelete='cascade')
    woo_id = fields.Integer(string='WooCommerce ID', required=True)
    woo_type = fields.Selection([
        ('simple', 'Simple'),
        ('variable', 'Variable'),
        ('grouped', 'Grouped'),
        ('external', 'External'),
    ], string='Woo Type', default='simple')
    product_tmpl_id = fields.Many2one('product.template', string='Odoo Product', ondelete='restrict')
    woo_status = fields.Selection([
        ('publish', 'Published'),
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('private', 'Private'),
    ], string='WooCommerce Status', default='publish')
    woo_sku = fields.Char(string='SKU')
    woo_regular_price = fields.Float(string='Regular Price')
    woo_sale_price = fields.Float(string='Sale Price')
    woo_stock_quantity = fields.Integer(string='Stock Qty')
    woo_stock_status = fields.Selection([
        ('instock', 'In Stock'),
        ('outofstock', 'Out of Stock'),
        ('onbackorder', 'On Backorder'),
    ], default='instock')
    woo_weight = fields.Float(string='Weight')
    woo_image_url = fields.Char(string='Image URL', help='Primary image URL from WooCommerce')
    woo_image = fields.Binary(string='Product Image', attachment=True)
    woo_category_ids = fields.Many2many('woo.product.category', string='WooCommerce Categories')
    variant_ids = fields.One2many('woo.product.variant', 'product_id', string='Variants')
    last_synced = fields.Datetime(string='Last Synced')
    sync_state = fields.Selection([
        ('synced', 'Synced'),
        ('pending', 'Pending Sync'),
        ('error', 'Sync Error'),
    ], default='pending')
    sync_error = fields.Text(string='Sync Error')

    # Cross-version constraint: Odoo 19 prefers models.Constraint, older uses _sql_constraints
    _sql_constraints = [
        ('woo_id_instance_unique', 'UNIQUE(woo_id, instance_id)',
         'WooCommerce product already exists for this instance.'),
    ]

    @api.onchange('woo_sku')
    def _onchange_woo_sku(self):
        """Keep the linked Odoo product's internal reference (default_code) in sync with woo_sku."""
        if self.woo_sku and self.product_tmpl_id:
            self.product_tmpl_id.default_code = self.woo_sku.strip()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.woo_sku and rec.product_tmpl_id:
                rec.product_tmpl_id.default_code = rec.woo_sku.strip()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'woo_sku' in vals and vals['woo_sku']:
            for rec in self:
                if rec.product_tmpl_id:
                    rec.product_tmpl_id.default_code = vals['woo_sku'].strip()
        return res

    @api.model
    def sync_products(self, instance):
        """Full product sync: import from WooCommerce, then export any flagged Odoo products."""
        self._import_products_from_woo(instance)
        # Only export if there are products explicitly flagged for WooCommerce sync
        flagged = self.env['product.template'].search_count([
            ('sync_to_woo', '=', True),
            ('company_id', '=', instance.company_id.id),
        ])
        if flagged:
            self._export_products_to_woo(instance)
        instance.last_product_sync = fields.Datetime.now()

    @api.model
    def _import_products_from_woo(self, instance):
        """Import/update products from WooCommerce into Odoo."""
        try:
            woo_products = instance._api_get_all('products', {'status': 'any'})
        except Exception as e:
            instance._log('error', f'Product import failed — could not fetch from API: {str(e)}')
            return

        instance._log('info', f'Fetched {len(woo_products)} products from WooCommerce, importing...')
        success = 0
        failed = 0
        for woo_product in woo_products:
            woo_id = woo_product.get('id', '?')
            name = woo_product.get('name', '?')
            try:
                with self.env.cr.savepoint():
                    self._process_woo_product(instance, woo_product)
                success += 1
            except Exception as e:
                failed += 1
                _logger.error(f'[WooConnector] Failed to import product [{woo_id}] "{name}": {str(e)}')

        instance._log('info', f'Product import complete: {success} succeeded, {failed} failed')

    def _process_woo_product(self, instance, data):
        """Create or update a WooCommerce product mapping in Odoo."""
        woo_id = data.get('id')
        if not woo_id:
            return

        existing = self.search([('woo_id', '=', woo_id), ('instance_id', '=', instance.id)], limit=1)

        # Sanitise status — only keep known selection values
        woo_status = data.get('status', 'publish')
        if woo_status not in ('publish', 'draft', 'pending', 'private'):
            woo_status = 'draft'

        # Sanitise type
        woo_type = data.get('type', 'simple')
        if woo_type not in ('simple', 'variable', 'grouped', 'external'):
            woo_type = 'simple'

        # Sanitise stock_status
        stock_status = data.get('stock_status', 'instock')
        if stock_status not in ('instock', 'outofstock', 'onbackorder'):
            stock_status = 'instock'

        vals = {
            'name': data.get('name') or 'Unnamed Product',
            'woo_id': woo_id,
            'instance_id': instance.id,
            'woo_type': woo_type,
            'woo_status': woo_status,
            'woo_sku': data.get('sku') or '',
            'woo_regular_price': float(data.get('regular_price') or 0),
            'woo_sale_price': float(data.get('sale_price') or 0),
            'woo_stock_quantity': int(data.get('stock_quantity') or 0),
            'woo_stock_status': stock_status,
            'woo_weight': float(data.get('weight') or 0),
            'woo_image_url': (data.get('images') or [{}])[0].get('src', ''),
            'last_synced': fields.Datetime.now(),
            'sync_state': 'synced',
        }

        # Resolve WooCommerce categories to local woo.product.category records
        woo_cat_ids = []
        for cat in (data.get('categories') or []):
            cat_woo_id = cat.get('id')
            if cat_woo_id:
                cat_rec = self.env['woo.product.category'].search([
                    ('woo_id', '=', cat_woo_id),
                    ('instance_id', '=', instance.id),
                ], limit=1)
                if cat_rec:
                    woo_cat_ids.append(cat_rec.id)
        if woo_cat_ids:
            vals['woo_category_ids'] = [(6, 0, woo_cat_ids)]

        # ── Find or create matching Odoo product.template ──────────────
        odoo_product = None

        # 1. Try existing woo mapping first (most reliable)
        if existing and existing.product_tmpl_id:
            odoo_product = existing.product_tmpl_id

        # 2. Try match by SKU
        if not odoo_product and data.get('sku'):
            odoo_product = self.env['product.template'].search(
                [('default_code', '=', data['sku'])], limit=1
            )

        # 3. Try match by exact name (for products without SKU)
        if not odoo_product and data.get('name'):
            odoo_product = self.env['product.template'].search(
                [('name', '=', data['name'])], limit=1
            )

        # 4. Create new Odoo product if still not found
        if not odoo_product and instance.create_products_in_odoo:
            # Strip HTML from descriptions safely
            import re
            def strip_html(html):
                return re.sub(r'<[^>]+>', '', html or '').strip()

            product_vals = self._safe_product_type_vals(instance, {
                'name': data.get('name') or 'Unnamed Product',
                'list_price': float(data.get('regular_price') or 0),
                'description_sale': strip_html(data.get('short_description', '')),
                'description': strip_html(data.get('description', '')),
                'sale_ok': True,
                'purchase_ok': True,
                'active': True,
            })

            # SKU
            if data.get('sku'):
                product_vals['default_code'] = data['sku'].strip()

            # Weight
            if data.get('weight'):
                try:
                    product_vals['weight'] = float(data['weight'])
                except (ValueError, TypeError):
                    pass

            # Inventory tracking: 'tracking' field (none/lot/serial) — only if stock module present
            product_tmpl_fields = self.env['product.template'].fields_get(['tracking'])
            if 'tracking' in product_tmpl_fields:
                product_vals['tracking'] = 'none'  # track by quantity only (no lot/serial)

            odoo_product = self.env['product.template'].create(product_vals)
            _logger.info(f'[WooConnector] Created Odoo product: {odoo_product.name} (id={odoo_product.id})')

            # Sync image right after creation
            if instance.sync_images and data.get('images'):
                image_url = data['images'][0].get('src')
                if image_url:
                    try:
                        resp = requests.get(image_url, timeout=15)
                        if resp.status_code == 200:
                            odoo_product.image_1920 = base64.b64encode(resp.content)
                    except Exception as img_e:
                        _logger.warning(f'[WooConnector] Image fetch failed: {img_e}')

        if odoo_product:
            vals['product_tmpl_id'] = odoo_product.id
            # Always sync key fields from WooCommerce → Odoo product on every import
            odoo_sync_vals = {}

            # Name
            woo_name = data.get('name', '').strip()
            if woo_name and woo_name != odoo_product.name:
                odoo_sync_vals['name'] = woo_name

            # Price
            woo_price = float(data.get('regular_price') or 0)
            if woo_price and abs(woo_price - odoo_product.list_price) > 0.001:
                odoo_sync_vals['list_price'] = woo_price

            # SKU — write unconditionally when WooCommerce has one
            # (default_code on product.template syncs to the single variant's product.product)
            woo_sku = (data.get('sku') or '').strip()
            current_sku = (odoo_product.default_code or '').strip()
            if woo_sku and woo_sku != current_sku:
                odoo_sync_vals['default_code'] = woo_sku
                _logger.info(
                    f'[WooConnector] Updating SKU for product {odoo_product.id} '
                    f'from "{current_sku}" to "{woo_sku}"'
                )

            if odoo_sync_vals:
                try:
                    odoo_product.write(odoo_sync_vals)
                    _logger.info(
                        f'[WooConnector] Synced fields {list(odoo_sync_vals.keys())} '
                        f'to Odoo product id={odoo_product.id}'
                    )
                except Exception as sync_e:
                    _logger.warning(
                        f'[WooConnector] Could not sync fields to Odoo product {odoo_product.id}: {sync_e}'
                    )

            # Ensure product is set up for inventory tracking if it's storable type
            # This fixes products created before this fix was applied
            try:
                product_fields = self.env['product.template'].fields_get(['tracking', 'type', 'detailed_type'])
                type_field = 'detailed_type' if 'detailed_type' in product_fields else 'type'
                current_type = odoo_product[type_field] if type_field in product_fields else ''
                if current_type == 'product' and 'tracking' in product_fields:
                    if not odoo_product.tracking or odoo_product.tracking == 'none':
                        pass  # 'none' is correct - track by qty, no lot/serial required
                    # Ensure product is active and saleable
                    tracking_fix = {}
                    if not odoo_product.active:
                        tracking_fix['active'] = True
                    if hasattr(odoo_product, 'sale_ok') and not odoo_product.sale_ok:
                        tracking_fix['sale_ok'] = True
                    if tracking_fix:
                        odoo_product.write(tracking_fix)
            except Exception:
                pass  # Non-critical, don't fail the import

        if existing:
            existing.write(vals)
            woo_rec = existing
            _logger.info(f'[WooConnector] Updated woo.product.template woo_id={woo_id}')
        else:
            woo_rec = self.create(vals)
            _logger.info(f'[WooConnector] Created woo.product.template woo_id={woo_id}')

        # Download and store the product image on the woo.product.template record
        image_url = vals.get('woo_image_url', '')
        if image_url and not woo_rec.woo_image:
            try:
                resp = requests.get(image_url, timeout=15)
                if resp.status_code == 200:
                    woo_rec.woo_image = base64.b64encode(resp.content)
                    # Also set on Odoo product if linked and no image yet
                    if odoo_product and not odoo_product.image_1920 and instance.sync_images:
                        odoo_product.image_1920 = base64.b64encode(resp.content)
            except Exception as img_e:
                _logger.warning(f'[WooConnector] Image fetch failed for woo_id={woo_id}: {img_e}')

        # Handle variants
        if woo_type == 'variable' and data.get('variations'):
            self._import_variants(instance, woo_id, odoo_product)

    def _import_variants(self, instance, woo_product_id, odoo_product):
        """Import product variants from WooCommerce."""
        try:
            variations = instance._api_get_all(f'products/{woo_product_id}/variations')
            woo_product_rec = self.search([
                ('woo_id', '=', woo_product_id),
                ('instance_id', '=', instance.id)
            ], limit=1)

            for var in variations:
                existing_var = self.env['woo.product.variant'].search([
                    ('woo_id', '=', var['id']),
                    ('product_id', '=', woo_product_rec.id),
                ], limit=1)
                var_vals = {
                    'woo_id': var['id'],
                    'product_id': woo_product_rec.id,
                    'sku': var.get('sku', ''),
                    'regular_price': float(var.get('regular_price') or 0),
                    'sale_price': float(var.get('sale_price') or 0),
                    'stock_quantity': var.get('stock_quantity') or 0,
                    'woo_attributes': str(var.get('attributes', [])),
                }
                if existing_var:
                    existing_var.write(var_vals)
                else:
                    self.env['woo.product.variant'].create(var_vals)
        except Exception as e:
            _logger.warning(f'Variant import error: {str(e)}')

    @api.model
    def _export_products_to_woo(self, instance):
        """Push Odoo products to WooCommerce (products tagged for woo sync)."""
        products = self.env['product.template'].search([
            ('sync_to_woo', '=', True),
            ('company_id', '=', instance.company_id.id),
        ])
        for product in products:
            self._push_product_to_woo(instance, product)

    def _push_product_to_woo(self, instance, product):
        """Create or update product in WooCommerce."""
        woo_mapping = self.search([
            ('product_tmpl_id', '=', product.id),
            ('instance_id', '=', instance.id),
        ], limit=1)

        payload = {
            'name': product.name,
            'sku': product.default_code or '',
            'regular_price': str(product.list_price),
            'description': product.description or '',
            'short_description': product.description_sale or '',
            'status': 'publish',
        }

        if instance.sync_stock:
            # qty_available is on product.product variants, not product.template
            if instance.warehouse_id:
                variants = product.with_context(
                    warehouse=instance.warehouse_id.id
                ).product_variant_ids
            else:
                variants = product.product_variant_ids
            qty = sum(v.qty_available for v in variants) if variants else 0.0
            payload['stock_quantity'] = int(qty)
            payload['manage_stock'] = True

        try:
            if woo_mapping and woo_mapping.woo_id:
                result = instance._api_put(f'products/{woo_mapping.woo_id}', payload)
                woo_mapping.write({'last_synced': fields.Datetime.now(), 'sync_state': 'synced'})
            else:
                result = instance._api_post('products', payload)
                if woo_mapping:
                    woo_mapping.write({
                        'woo_id': result['id'],
                        'last_synced': fields.Datetime.now(),
                        'sync_state': 'synced',
                    })
                else:
                    self.create({
                        'name': product.name,
                        'woo_id': result['id'],
                        'instance_id': instance.id,
                        'product_tmpl_id': product.id,
                        'sync_state': 'synced',
                        'last_synced': fields.Datetime.now(),
                    })
        except Exception as e:
            instance._log('error', f'Product push failed for {product.name}: {str(e)}')

    @api.model
    def sync_stock_to_woo(self, instance):
        """Push current Odoo stock quantities to WooCommerce for ALL mapped products."""
        mappings = self.search([('instance_id', '=', instance.id), ('woo_id', '!=', False)])
        instance._log('info', f'Syncing stock for {len(mappings)} products')
        mappings._sync_stock_to_woo_for_mappings(instance)

    def _sync_stock_to_woo_for_mappings(self, instance):
        """
        Push stock for this recordset of woo.product.template mappings.
        Called by sync_stock_to_woo (full sync) and button_validate hook (affected products only).
        """
        mappings = self
        success = 0
        failed = 0
        for mapping in mappings:
            if not mapping.product_tmpl_id:
                continue
            try:
                tmpl = mapping.product_tmpl_id

                # Get qty from product.product variants (most reliable across Odoo versions)
                # product.template.qty_available is a computed sum but may not reflect
                # warehouse context correctly; summing variants directly is more explicit.
                try:
                    if instance.warehouse_id:
                        variants = tmpl.with_context(
                            warehouse=instance.warehouse_id.id
                        ).product_variant_ids
                    else:
                        variants = tmpl.product_variant_ids

                    if variants:
                        qty = sum(v.qty_available for v in variants)
                    else:
                        # Fallback: read directly from template (works for single-variant)
                        qty = float(getattr(tmpl.with_context(
                            warehouse=instance.warehouse_id.id
                            if instance.warehouse_id else {}
                        ), 'qty_available', 0) or 0)
                except Exception:
                    qty = 0.0

                _logger.info(
                    f'[WooConnector] Pushing stock for {mapping.name} '
                    f'(woo_id={mapping.woo_id}): qty={int(qty)}'
                )

                # Prefer woo_sku (the field users edit on the mapping record).
                # Fall back to product default_code if woo_sku is empty.
                sku = (mapping.woo_sku or '').strip()
                if not sku and mapping.product_tmpl_id:
                    sku = (mapping.product_tmpl_id.default_code or '').strip()

                woo_payload = {'stock_quantity': int(qty), 'manage_stock': True}
                if sku:
                    woo_payload['sku'] = sku

                result = instance._api_put(f'products/{mapping.woo_id}', woo_payload)
                # Confirm WooCommerce accepted the update
                if isinstance(result, dict) and result.get('id'):
                    mapping.woo_stock_quantity = int(qty)
                    success += 1
                else:
                    _logger.warning(
                        f'[WooConnector] Unexpected response for stock update '
                        f'woo_id={mapping.woo_id}: {result}'
                    )
                    success += 1  # API didn't error, treat as success
            except Exception as e:
                failed += 1
                _logger.error(
                    f'[WooConnector] Stock sync failed for {mapping.name} '
                    f'(woo_id={mapping.woo_id}): {str(e)}'
                )
                instance._log('error', f'Stock sync failed for {mapping.name}: {str(e)}')

        instance.last_stock_sync = fields.Datetime.now()
        instance._log(
            'info' if not failed else 'warning',
            f'Stock sync complete: {success} pushed, {failed} failed out of {len(mappings)} products'
        )


class WooProductVariant(models.Model):
    _name = 'woo.product.variant'
    _description = 'WooCommerce Product Variant'

    product_id = fields.Many2one('woo.product.template', string='WooCommerce Product', ondelete='cascade')
    woo_id = fields.Integer(string='WooCommerce Variant ID')
    odoo_variant_id = fields.Many2one('product.product', string='Odoo Variant')
    sku = fields.Char(string='SKU')
    regular_price = fields.Float(string='Regular Price')
    sale_price = fields.Float(string='Sale Price')
    stock_quantity = fields.Integer(string='Stock Quantity')
    woo_attributes = fields.Text(string='Attributes (raw)')


class WooProductCategory(models.Model):
    _name = 'woo.product.category'
    _description = 'WooCommerce Product Category'

    name = fields.Char(required=True)
    woo_id = fields.Integer(string='WooCommerce Category ID')
    instance_id = fields.Many2one('woo.instance', string='Instance')
    odoo_category_id = fields.Many2one('product.category', string='Odoo Category')
    parent_id = fields.Many2one('woo.product.category', string='Parent Category')
    slug = fields.Char(string='Slug')
    description = fields.Text(string='Description')
    image_url = fields.Char(string='Image URL')
    count = fields.Integer(string='Product Count')

    @api.model
    def sync_categories_from_woo(self, instance):
        """Import all product categories from WooCommerce into Odoo."""
        instance._log('info', 'Starting product category sync from WooCommerce')
        try:
            total_synced = 0
            categories = instance._api_get_all('products/categories', params={
                'orderby': 'id',
                'order': 'asc',
            })
            for cat in categories:
                self._process_woo_category(instance, cat)
                total_synced += 1

            # Second pass: resolve parent relationships now all records exist
            all_woo_cats = self.search([('instance_id', '=', instance.id), ('woo_id', '!=', 0)])
            for woo_cat in all_woo_cats:
                raw = self.env.context.get(f'_woo_parent_{woo_cat.id}')
                if raw:
                    parent = self.search([
                        ('woo_id', '=', raw),
                        ('instance_id', '=', instance.id),
                    ], limit=1)
                    if parent:
                        woo_cat.parent_id = parent.id

            instance._log('success', f'Product category sync complete: {total_synced} categories synced')

        except Exception as e:
            instance._log('error', f'Category sync failed: {str(e)}')
            raise

    def _process_woo_category(self, instance, data):
        """Create or update a single WooCommerce category record."""
        woo_id = data.get('id')
        if not woo_id:
            return

        existing = self.search([
            ('woo_id', '=', woo_id),
            ('instance_id', '=', instance.id),
        ], limit=1)

        vals = {
            'name': data.get('name', ''),
            'woo_id': woo_id,
            'instance_id': instance.id,
            'slug': data.get('slug', ''),
            'description': data.get('description', ''),
            'count': data.get('count', 0),
            'image_url': data.get('image', {}).get('src', '') if data.get('image') else '',
        }

        # Match or create the Odoo product category
        odoo_cat = self.env['product.category'].search(
            [('name', '=', data.get('name', ''))], limit=1
        )
        if not odoo_cat:
            odoo_cat = self.env['product.category'].create({
                'name': data.get('name', ''),
            })
        vals['odoo_category_id'] = odoo_cat.id

        if existing:
            existing.write(vals)
        else:
            self.create(vals)