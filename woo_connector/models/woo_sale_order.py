# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.fields import Command

_logger = logging.getLogger(__name__)

WOO_STATUS_MAP = {
    'pending': 'draft',
    'processing': 'sale',
    'on-hold': 'draft',
    'completed': 'done',
    'cancelled': 'cancel',
    'refunded': 'cancel',
    'failed': 'cancel',
}

def _safe_product_type_vals_fn(env, instance, base_vals):
    """Module-level helper: returns base_vals with the correct type field for this Odoo version."""
    product_tmpl_fields = env['product.template'].fields_get(['type', 'detailed_type'])
    type_field = 'detailed_type' if 'detailed_type' in product_tmpl_fields else 'type'
    desired = instance.default_product_type
    valid_values = [v[0] for v in product_tmpl_fields.get(type_field, {}).get('selection', [])]
    if valid_values and desired not in valid_values:
        desired = 'consu' if 'consu' in valid_values else (valid_values[0] if valid_values else 'consu')
    return dict(base_vals, **{type_field: desired})


class WooSaleOrder(models.Model):
    """Links a WooCommerce order record to an Odoo sale.order."""
    _name = 'woo.sale.order'
    _inherit = ['woo.mixin']
    _description = 'WooCommerce Order'
    _rec_name = 'woo_order_id'

    instance_id = fields.Many2one('woo.instance', string='Instance', required=True, ondelete='cascade')
    woo_order_id = fields.Integer(string='WooCommerce Order ID', required=True)
    woo_order_number = fields.Char(string='WooCommerce Order Number')
    woo_order_status = fields.Char(string='WooCommerce Status')
    sale_order_id = fields.Many2one('sale.order', string='Odoo Sale Order', ondelete='restrict')
    synced_date = fields.Datetime(string='Synced Date', default=fields.Datetime.now)
    last_updated = fields.Datetime(string='Last Updated')
    payment_method = fields.Char(string='Payment Method')
    payment_method_title = fields.Char(string='Payment Method Title')
    woo_currency = fields.Char(string='WooCommerce Currency')
    woo_total = fields.Float(string='WooCommerce Total')
    woo_discount_total = fields.Float(string='Discount Total')
    woo_shipping_total = fields.Float(string='Shipping Total')
    woo_tax_total = fields.Float(string='Tax Total')

    _sql_constraints = [
        ('woo_order_instance_unique', 'unique(woo_order_id, instance_id)',
         'This WooCommerce order is already imported.')
    ]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    woo_instance_id = fields.Many2one('woo.instance', string='WooCommerce Instance')
    woo_order_id = fields.Integer(string='WooCommerce Order ID')
    woo_order_number = fields.Char(string='WooCommerce Order #')
    woo_order_status = fields.Char(string='WooCommerce Status')
    woo_payment_method = fields.Char(string='WooCommerce Payment')
    is_woo_order = fields.Boolean(string='Is WooCommerce Order', default=False)
    woo_coupon_code = fields.Char(string='Coupon Code')

    @api.model
    def import_orders_from_woo(self, instance):
        """Import orders from WooCommerce."""
        params = {'orderby': 'date', 'order': 'asc', 'per_page': 50}

        # Only fetch orders since last sync
        if instance.last_order_sync:
            params['after'] = instance.last_order_sync.strftime('%Y-%m-%dT%H:%M:%S')

        try:
            # Filter by configured statuses
            statuses = instance.import_order_status_ids.mapped('code')
            if statuses:
                params['status'] = ','.join(statuses)
            else:
                params['status'] = 'processing,completed,on-hold,pending'

            woo_orders = instance._api_get_all('orders', params)
            instance._log('info', f'Fetched {len(woo_orders)} orders from WooCommerce')

            created_count = 0
            updated_count = 0
            for woo_order in woo_orders:
                result = self._process_woo_order(instance, woo_order)
                if result == 'created':
                    created_count += 1
                elif result == 'updated':
                    updated_count += 1

            instance.last_order_sync = fields.Datetime.now()
            instance._log('info', f'Order sync done: {created_count} created, {updated_count} updated')

        except Exception as e:
            instance._log('error', f'Order import failed: {str(e)}')
            raise

    def _process_woo_order(self, instance, data):
        """Create or update Odoo sale order from WooCommerce order data."""
        woo_order_id = data.get('id')

        # Check idempotency
        existing_mapping = self.env['woo.sale.order'].search([
            ('woo_order_id', '=', woo_order_id),
            ('instance_id', '=', instance.id),
        ], limit=1)

        if existing_mapping and existing_mapping.sale_order_id:
            # Update status only for existing
            self._update_order_status(existing_mapping, data)
            return 'updated'

        # Create customer
        partner = self._get_or_create_partner(instance, data)

        # Build sale order
        order_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': self._get_billing_address(instance, data, partner),
            'partner_shipping_id': self._get_shipping_address(instance, data, partner),
            'woo_instance_id': instance.id,
            'woo_order_id': woo_order_id,
            'woo_order_number': data.get('number', str(woo_order_id)),
            'woo_order_status': data.get('status'),
            'woo_payment_method': data.get('payment_method_title', ''),
            'woo_coupon_code': ','.join([c.get('code', '') for c in data.get('coupon_lines', [])]),
            'is_woo_order': True,
            'client_order_ref': f"{instance.order_prefix}{data.get('number', woo_order_id)}",
            'note': data.get('customer_note', ''),
            'currency_id': self._get_currency(data.get('currency', 'USD')).id,
        }

        # Set pricelist if configured
        if instance.pricelist_id:
            order_vals['pricelist_id'] = instance.pricelist_id.id

        order = self.create(order_vals)

        # Create order lines
        for line_item in data.get('line_items', []):
            self._create_order_line(instance, order, line_item)

        # Add shipping line
        for shipping in data.get('shipping_lines', []):
            self._create_shipping_line(instance, order, shipping)

        # Add fee lines (e.g., surcharges)
        for fee in data.get('fee_lines', []):
            self._create_fee_line(instance, order, fee)

        # Add discount / coupon
        total_discount = float(data.get('discount_total', 0))
        if total_discount > 0:
            self._apply_discount(instance, order, total_discount, data.get('coupon_lines', []))

        # Confirm order
        if instance.auto_confirm_order and data.get('status') not in ('pending', 'on-hold'):
            order.action_confirm()

        # Create invoice if configured
        if instance.auto_create_invoice and data.get('status') == 'completed':
            invoice = order._create_invoices()
            if instance.auto_validate_invoice and invoice:
                invoice.action_post()

        # Create mapping record
        self.env['woo.sale.order'].create({
            'instance_id': instance.id,
            'woo_order_id': woo_order_id,
            'woo_order_number': str(data.get('number', woo_order_id)),
            'woo_order_status': data.get('status'),
            'sale_order_id': order.id,
            'payment_method': data.get('payment_method', ''),
            'payment_method_title': data.get('payment_method_title', ''),
            'woo_currency': data.get('currency', ''),
            'woo_total': float(data.get('total', 0)),
            'woo_discount_total': float(data.get('discount_total', 0)),
            'woo_shipping_total': float(data.get('shipping_total', 0)),
            'woo_tax_total': float(data.get('total_tax', 0)),
        })

        instance._log('info', f'Created order {order.name} from WooCommerce #{woo_order_id}',
                      model='sale.order', res_id=order.id)
        return 'created'

    def _get_or_create_partner(self, instance, data):
        """Find or create Odoo partner from WooCommerce order data."""
        billing = data.get('billing', {})
        email = billing.get('email', '')
        phone = billing.get('phone', '')
        woo_customer_id = data.get('customer_id', 0)

        # Search by WooCommerce customer ID first
        if woo_customer_id:
            partner = self.env['res.partner'].search([
                ('woo_customer_id', '=', woo_customer_id),
                ('woo_instance_id', '=', instance.id),
            ], limit=1)
            if partner:
                return partner

        # Search by email
        if email:
            partner = self.env['res.partner'].search([('email', '=', email)], limit=1)
            if partner:
                return partner

        # Create new partner
        country = self.env['res.country'].search(
            [('code', '=', billing.get('country', ''))], limit=1
        )
        state = self.env['res.country.state'].search([
            ('code', '=', billing.get('state', '')),
            ('country_id', '=', country.id),
        ], limit=1) if country else self.env['res.country.state']

        partner_vals = {
            'name': f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
                    or billing.get('company', 'Unknown Customer'),
            'email': email,
            'phone': phone,
            'street': billing.get('address_1', ''),
            'street2': billing.get('address_2', ''),
            'city': billing.get('city', ''),
            'zip': billing.get('postcode', ''),
            'country_id': country.id if country else False,
            'state_id': state.id if state else False,
            'company_name': billing.get('company', ''),
            'customer_rank': 1,
            'woo_customer_id': woo_customer_id,
            'woo_instance_id': instance.id,
        }
        return self.env['res.partner'].create(partner_vals)

    def _get_billing_address(self, instance, data, partner):
        """Return billing address partner id."""
        return partner.id

    def _get_shipping_address(self, instance, data, partner):
        """Create or return shipping address."""
        shipping = data.get('shipping', {})
        if not shipping.get('address_1'):
            return partner.id

        country = self.env['res.country'].search(
            [('code', '=', shipping.get('country', ''))], limit=1
        )
        existing = self.env['res.partner'].search([
            ('parent_id', '=', partner.id),
            ('type', '=', 'delivery'),
            ('street', '=', shipping.get('address_1', '')),
        ], limit=1)

        if existing:
            return existing.id

        state = self.env['res.country.state'].search([
            ('code', '=', shipping.get('state', '')),
            ('country_id', '=', country.id),
        ], limit=1) if country else self.env['res.country.state']

        ship_partner = self.env['res.partner'].create({
            'name': f"{shipping.get('first_name', '')} {shipping.get('last_name', '')}".strip()
                    or partner.name,
            'parent_id': partner.id,
            'type': 'delivery',
            'street': shipping.get('address_1', ''),
            'street2': shipping.get('address_2', ''),
            'city': shipping.get('city', ''),
            'zip': shipping.get('postcode', ''),
            'country_id': country.id if country else False,
            'state_id': state.id if state else False,
        })
        return ship_partner.id

    def _create_order_line(self, instance, order, line_item):
        """Create a sale.order.line from a WooCommerce line item."""
        product = None
        sku = line_item.get('sku', '')
        woo_product_id = line_item.get('product_id')

        # Find product by SKU
        if sku:
            product_tmpl = self.env['product.template'].search(
                [('default_code', '=', sku)], limit=1
            )
            if product_tmpl:
                product = product_tmpl.product_variant_id

        # Find by woo mapping
        if not product and woo_product_id:
            woo_mapping = self.env['woo.product.template'].search([
                ('woo_id', '=', woo_product_id),
                ('instance_id', '=', instance.id),
            ], limit=1)
            if woo_mapping and woo_mapping.product_tmpl_id:
                product = woo_mapping.product_tmpl_id.product_variant_id

        # Fallback: create generic product
        if not product and instance.create_products_in_odoo:
            tmpl = self.env['product.template'].create(
                _safe_product_type_vals_fn(self.env, instance, {
                    'name': line_item.get('name', 'WooCommerce Product'),
                    'default_code': sku,
                    'list_price': float(line_item.get('price', 0)),
                })
            )
            product = tmpl.product_variant_id

        if not product:
            instance._log('warning', f"Product not found for line item: {line_item.get('name')}")
            return

        tax_ids = self._get_taxes_for_line(instance, line_item)

        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': product.id,
            'name': line_item.get('name', product.name),
            'product_uom_qty': float(line_item.get('quantity', 1)),
            'price_unit': float(line_item.get('price', 0)),
            'tax_ids': [(6, 0, tax_ids)],
        })

    def _create_shipping_line(self, instance, order, shipping):
        """Add shipping as a service product line."""
        shipping_product = self.env.ref(
            'delivery.product_product_delivery', raise_if_not_found=False
        )
        if not shipping_product:
            shipping_product = self.env['product.product'].search(
                [('type', '=', 'service'), ('name', 'ilike', 'Shipping')], limit=1
            )
        if not shipping_product:
            tmpl = self.env['product.template'].create({
                'name': 'Shipping',
                'type': 'service',
            })
            shipping_product = tmpl.product_variant_id

        total = float(shipping.get('total', 0))
        if total > 0:
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': shipping_product.id,
                'name': shipping.get('method_title', 'Shipping'),
                'product_uom_qty': 1,
                'price_unit': total,
            })

    def _create_fee_line(self, instance, order, fee):
        """Add fee lines (COD fees, handling, etc.)."""
        fee_product = self.env['product.product'].search(
            [('name', '=', 'WooCommerce Fee'), ('type', '=', 'service')], limit=1
        )
        if not fee_product:
            tmpl = self.env['product.template'].create({
                'name': 'WooCommerce Fee',
                'type': 'service',
            })
            fee_product = tmpl.product_variant_id

        total = float(fee.get('total', 0))
        if total:
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': fee_product.id,
                'name': fee.get('name', 'Fee'),
                'product_uom_qty': 1,
                'price_unit': total,
            })

    def _apply_discount(self, instance, order, discount_total, coupon_lines):
        """Apply discount line for coupon/cart discount."""
        discount_product = self.env['product.product'].search(
            [('name', '=', 'WooCommerce Discount'), ('type', '=', 'service')], limit=1
        )
        if not discount_product:
            tmpl = self.env['product.template'].create({
                'name': 'WooCommerce Discount',
                'type': 'service',
            })
            discount_product = tmpl.product_variant_id

        coupon_codes = ', '.join([c.get('code', '') for c in coupon_lines])
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': discount_product.id,
            'name': f"Discount{' (' + coupon_codes + ')' if coupon_codes else ''}",
            'product_uom_qty': 1,
            'price_unit': -discount_total,
        })

    def _get_taxes_for_line(self, instance, line_item):
        """Map WooCommerce taxes to Odoo taxes."""
        tax_ids = []
        for woo_tax in line_item.get('taxes', []):
            woo_rate_id = woo_tax.get('rate_id')
            if woo_rate_id:
                mapping = instance.tax_mapping_ids.filtered(
                    lambda t: t.woo_tax_rate_id == str(woo_rate_id)
                )
                if mapping and mapping.odoo_tax_id:
                    tax_ids.append(mapping.odoo_tax_id.id)
        return tax_ids

    def _update_order_status(self, mapping, data):
        """Update existing order status from WooCommerce."""
        mapping.write({
            'woo_order_status': data.get('status'),
            'last_updated': fields.Datetime.now(),
        })
        if mapping.sale_order_id:
            mapping.sale_order_id.write({
                'woo_order_status': data.get('status'),
            })

    def _get_currency(self, currency_code):
        currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
        if not currency:
            currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
        return currency

    def action_push_status_to_woo(self):
        """Push Odoo order status back to WooCommerce."""
        self.ensure_one()
        if not self.is_woo_order or not self.woo_instance_id:
            raise UserError(_('This is not a WooCommerce order.'))

        status_map = {
            'draft': 'pending',
            'sale': 'processing',
            'done': 'completed',
            'cancel': 'cancelled',
        }
        woo_status = status_map.get(self.state, 'processing')
        try:
            self.woo_instance_id._api_put(f'orders/{self.woo_order_id}', {
                'status': woo_status
            })
            self.woo_order_status = woo_status
        except Exception as e:
            raise UserError(str(e))
