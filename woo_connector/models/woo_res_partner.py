# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    woo_customer_id = fields.Integer(string='WooCommerce Customer ID')
    woo_instance_id = fields.Many2one('woo.instance', string='WooCommerce Instance')
    is_woo_customer = fields.Boolean(string='Is WooCommerce Customer', default=False)

    @api.model
    def import_customers_from_woo(self, instance):
        """Import all WooCommerce customers into Odoo."""
        try:
            customers = instance._api_get_all('customers')
            instance._log('info', f'Importing {len(customers)} customers')
            for cust in customers:
                self._process_woo_customer(instance, cust)
        except Exception as e:
            instance._log('error', f'Customer import failed: {str(e)}')

    def _process_woo_customer(self, instance, data):
        """Create or update Odoo partner from WooCommerce customer."""
        woo_id = data.get('id')
        email = data.get('email', '')

        # Check by woo_customer_id
        existing = self.search([
            ('woo_customer_id', '=', woo_id),
            ('woo_instance_id', '=', instance.id),
        ], limit=1)

        if not existing and email:
            existing = self.search([('email', '=', email)], limit=1)

        billing = data.get('billing', {})
        country = self.env['res.country'].search(
            [('code', '=', billing.get('country', ''))], limit=1
        )

        vals = {
            'name': f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
                    or data.get('username', 'Unknown'),
            'email': email,
            'phone': billing.get('phone', ''),
            'street': billing.get('address_1', ''),
            'street2': billing.get('address_2', ''),
            'city': billing.get('city', ''),
            'zip': billing.get('postcode', ''),
            'country_id': country.id if country else False,
            'customer_rank': 1,
            'woo_customer_id': woo_id,
            'woo_instance_id': instance.id,
            'is_woo_customer': True,
        }

        if existing:
            existing.write(vals)
        else:
            self.create(vals)
