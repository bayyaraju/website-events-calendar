# -*- coding: utf-8 -*-
from unittest.mock import patch, MagicMock
from odoo.tests.common import TransactionCase


class TestWooProduct(TransactionCase):

    def setUp(self):
        super().setUp()
        self.instance = self.env['woo.instance'].create({
            'name': 'Test Store',
            'store_url': 'https://teststore.example.com',
            'consumer_key': 'ck_test',
            'consumer_secret': 'cs_test',
            'company_id': self.env.company.id,
            'create_products_in_odoo': True,
            'sync_images': False,
        })

    def _make_woo_product_data(self, **kwargs):
        data = {
            'id': 101,
            'name': 'Test Product',
            'type': 'simple',
            'status': 'publish',
            'sku': 'TEST-001',
            'regular_price': '99.99',
            'sale_price': '79.99',
            'stock_quantity': 50,
            'stock_status': 'instock',
            'weight': '0.5',
            'images': [],
            'line_items': [],
        }
        data.update(kwargs)
        return data

    def test_create_product_mapping(self):
        """Test creating a WooCommerce product mapping."""
        data = self._make_woo_product_data()
        WooProduct = self.env['woo.product.template']
        WooProduct._process_woo_product(self.instance, data)

        mapping = WooProduct.search([
            ('woo_id', '=', 101),
            ('instance_id', '=', self.instance.id),
        ])
        self.assertEqual(len(mapping), 1)
        self.assertEqual(mapping.name, 'Test Product')
        self.assertEqual(mapping.woo_sku, 'TEST-001')
        self.assertAlmostEqual(mapping.woo_regular_price, 99.99)

    def test_odoo_product_created(self):
        """Test that Odoo product is auto-created when enabled."""
        data = self._make_woo_product_data(sku='AUTO-PROD-001')
        self.env['woo.product.template']._process_woo_product(self.instance, data)

        odoo_product = self.env['product.template'].search([
            ('default_code', '=', 'AUTO-PROD-001')
        ])
        self.assertTrue(odoo_product)
        self.assertEqual(odoo_product.name, 'Test Product')

    def test_existing_odoo_product_used(self):
        """Test that existing Odoo product is linked when SKU matches."""
        existing = self.env['product.template'].create({
            'name': 'Existing Product',
            'default_code': 'EXIST-001',
            'type': 'consu',
        })
        data = self._make_woo_product_data(sku='EXIST-001', id=202)
        self.env['woo.product.template']._process_woo_product(self.instance, data)

        mapping = self.env['woo.product.template'].search([
            ('woo_id', '=', 202),
            ('instance_id', '=', self.instance.id),
        ])
        self.assertEqual(mapping.product_tmpl_id.id, existing.id)

    def test_duplicate_product_not_created(self):
        """Test idempotency: re-processing same product doesn't duplicate."""
        data = self._make_woo_product_data()
        WooProduct = self.env['woo.product.template']
        WooProduct._process_woo_product(self.instance, data)
        WooProduct._process_woo_product(self.instance, data)

        mappings = WooProduct.search([
            ('woo_id', '=', 101),
            ('instance_id', '=', self.instance.id),
        ])
        self.assertEqual(len(mappings), 1)

    def test_product_no_odoo_create_when_disabled(self):
        """Test that Odoo product is NOT created when create_products_in_odoo is False."""
        self.instance.create_products_in_odoo = False
        data = self._make_woo_product_data(sku='NOAUTO-SKU', id=999)
        self.env['woo.product.template']._process_woo_product(self.instance, data)

        odoo_product = self.env['product.template'].search([
            ('default_code', '=', 'NOAUTO-SKU')
        ])
        self.assertFalse(odoo_product)
