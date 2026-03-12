# -*- coding: utf-8 -*-
from unittest.mock import patch, MagicMock
from odoo.tests.common import TransactionCase


class TestWooOrder(TransactionCase):

    def setUp(self):
        super().setUp()
        self.instance = self.env['woo.instance'].create({
            'name': 'Test Store',
            'store_url': 'https://teststore.example.com',
            'consumer_key': 'ck_test',
            'consumer_secret': 'cs_test',
            'company_id': self.env.company.id,
            'auto_confirm_order': False,
            'order_prefix': 'WOO-',
        })
        # Create test product
        self.product_tmpl = self.env['product.template'].create({
            'name': 'Test Product',
            'default_code': 'SKU-TEST',
            'type': 'consu',
            'list_price': 50.0,
        })

    def _make_order_data(self, **kwargs):
        data = {
            'id': 1001,
            'number': '1001',
            'status': 'processing',
            'currency': 'USD',
            'total': '100.00',
            'discount_total': '0.00',
            'shipping_total': '10.00',
            'total_tax': '5.00',
            'payment_method': 'paypal',
            'payment_method_title': 'PayPal',
            'customer_id': 0,
            'customer_note': '',
            'billing': {
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'john@example.com',
                'phone': '1234567890',
                'address_1': '123 Main St',
                'address_2': '',
                'city': 'Mumbai',
                'state': 'MH',
                'postcode': '400001',
                'country': 'IN',
                'company': '',
            },
            'shipping': {
                'first_name': 'John',
                'last_name': 'Doe',
                'address_1': '123 Main St',
                'address_2': '',
                'city': 'Mumbai',
                'state': 'MH',
                'postcode': '400001',
                'country': 'IN',
            },
            'line_items': [
                {
                    'id': 1,
                    'name': 'Test Product',
                    'product_id': 0,
                    'sku': 'SKU-TEST',
                    'quantity': 2,
                    'price': '45.00',
                    'taxes': [],
                }
            ],
            'shipping_lines': [],
            'fee_lines': [],
            'coupon_lines': [],
        }
        data.update(kwargs)
        return data

    def test_order_created(self):
        """Test that a WooCommerce order creates a sale order."""
        data = self._make_order_data()
        result = self.env['sale.order']._process_woo_order(self.instance, data)
        self.assertEqual(result, 'created')

        order = self.env['sale.order'].search([
            ('woo_order_id', '=', 1001),
        ])
        self.assertTrue(order)
        self.assertTrue(order.is_woo_order)
        self.assertEqual(order.woo_order_status, 'processing')

    def test_order_idempotency(self):
        """Test that processing same order twice doesn't duplicate."""
        data = self._make_order_data()
        self.env['sale.order']._process_woo_order(self.instance, data)
        result = self.env['sale.order']._process_woo_order(self.instance, data)
        self.assertEqual(result, 'updated')

        orders = self.env['sale.order'].search([('woo_order_id', '=', 1001)])
        self.assertEqual(len(orders), 1)

    def test_customer_created(self):
        """Test that customer is created from billing info."""
        data = self._make_order_data()
        self.env['sale.order']._process_woo_order(self.instance, data)

        partner = self.env['res.partner'].search([('email', '=', 'john@example.com')])
        self.assertTrue(partner)
        self.assertEqual(partner[0].name, 'John Doe')

    def test_customer_not_duplicated(self):
        """Test that existing customer by email is reused."""
        # Pre-create customer
        existing = self.env['res.partner'].create({
            'name': 'John Doe',
            'email': 'john@example.com',
            'customer_rank': 1,
        })
        data = self._make_order_data()
        self.env['sale.order']._process_woo_order(self.instance, data)

        partners = self.env['res.partner'].search([('email', '=', 'john@example.com')])
        self.assertEqual(len(partners), 1)
        self.assertEqual(partners[0].id, existing.id)

    def test_order_line_created_from_sku(self):
        """Test that order lines are created from SKU match."""
        data = self._make_order_data()
        self.env['sale.order']._process_woo_order(self.instance, data)

        order = self.env['sale.order'].search([('woo_order_id', '=', 1001)])
        self.assertTrue(order.order_line)
        line = order.order_line[0]
        self.assertEqual(line.product_id.default_code, 'SKU-TEST')
        self.assertEqual(line.product_uom_qty, 2)
        self.assertAlmostEqual(line.price_unit, 45.0)

    def test_discount_applied(self):
        """Test that WooCommerce discount creates negative order line."""
        data = self._make_order_data(
            discount_total='10.00',
            coupon_lines=[{'code': 'SAVE10'}]
        )
        self.env['sale.order']._process_woo_order(self.instance, data)

        order = self.env['sale.order'].search([('woo_order_id', '=', 1001)])
        discount_line = order.order_line.filtered(lambda l: l.price_unit < 0)
        self.assertTrue(discount_line)
        self.assertAlmostEqual(abs(discount_line.price_unit), 10.0)

    def test_order_mapping_record_created(self):
        """Test that woo.sale.order mapping record is created."""
        data = self._make_order_data()
        self.env['sale.order']._process_woo_order(self.instance, data)

        mapping = self.env['woo.sale.order'].search([
            ('woo_order_id', '=', 1001),
            ('instance_id', '=', self.instance.id),
        ])
        self.assertTrue(mapping)
        self.assertAlmostEqual(mapping.woo_total, 100.0)
