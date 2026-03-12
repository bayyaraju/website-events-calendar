# -*- coding: utf-8 -*-
from unittest.mock import patch, MagicMock
from odoo.tests.common import TransactionCase


class TestWooInstance(TransactionCase):

    def setUp(self):
        super().setUp()
        self.instance = self.env['woo.instance'].create({
            'name': 'Test Store',
            'store_url': 'https://teststore.example.com',
            'consumer_key': 'ck_test123',
            'consumer_secret': 'cs_test456',
            'company_id': self.env.company.id,
        })

    def test_instance_created(self):
        """Test that instance is created with correct defaults."""
        self.assertEqual(self.instance.name, 'Test Store')
        self.assertEqual(self.instance.state, 'draft')
        self.assertTrue(self.instance.active)
        self.assertTrue(self.instance.auto_confirm_order)
        self.assertEqual(self.instance.order_prefix, 'WOO-')

    def test_get_api_url(self):
        """Test API URL construction."""
        url = self.instance._get_api_url('orders')
        self.assertIn('wc/v3/orders', url)
        self.assertIn('teststore.example.com', url)

    def test_get_api_url_trailing_slash(self):
        """Test URL handles trailing slash on store URL."""
        self.instance.store_url = 'https://teststore.example.com/'
        url = self.instance._get_api_url('products')
        self.assertNotIn('//', url.replace('https://', ''))

    @patch('requests.request')
    def test_api_call_success(self, mock_request):
        """Test successful API call."""
        mock_response = MagicMock()
        mock_response.json.return_value = [{'id': 1, 'name': 'Test'}]
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.instance._api_call('GET', 'orders')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], 1)

    @patch('requests.request')
    def test_api_call_timeout(self, mock_request):
        """Test API call timeout handling."""
        import requests
        mock_request.side_effect = requests.exceptions.Timeout()
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.instance._api_call('GET', 'orders')

    def test_logging(self):
        """Test that logging works correctly."""
        self.instance._log('info', 'Test log message')
        log = self.env['woo.log'].search([
            ('instance_id', '=', self.instance.id),
            ('message', '=', 'Test log message'),
        ], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.level, 'info')

    def test_webhook_signature_no_secret(self):
        """Test webhook validation passes when no secret configured."""
        result = self.instance.validate_webhook_signature(b'payload', 'any_sig')
        self.assertTrue(result)

    def test_webhook_signature_valid(self):
        """Test webhook HMAC validation."""
        import hmac
        import hashlib
        import base64
        self.instance.webhook_secret = 'my_secret'
        payload = b'{"id": 1}'
        computed = hmac.new(b'my_secret', payload, hashlib.sha256).digest()
        sig = base64.b64encode(computed).decode()
        result = self.instance.validate_webhook_signature(payload, sig)
        self.assertTrue(result)

    def test_webhook_signature_invalid(self):
        """Test that invalid webhook signature is rejected."""
        self.instance.webhook_secret = 'my_secret'
        result = self.instance.validate_webhook_signature(b'payload', 'wrong_sig')
        self.assertFalse(result)

    def test_stats_zero_on_new_instance(self):
        """Test that stats are zero for new instance."""
        self.instance._compute_stats()
        self.assertEqual(self.instance.total_orders_synced, 0)
        self.assertEqual(self.instance.total_products_synced, 0)
