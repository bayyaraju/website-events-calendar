# -*- coding: utf-8 -*-
from odoo import api, fields, models


class WooTax(models.Model):
    _name = 'woo.tax'
    _description = 'WooCommerce Tax Mapping'

    instance_id = fields.Many2one('woo.instance', string='Instance', required=True, ondelete='cascade')
    name = fields.Char(string='WooCommerce Tax Name', required=True)
    woo_tax_rate_id = fields.Char(string='WooCommerce Rate ID')
    woo_tax_class = fields.Char(string='WooCommerce Tax Class')
    woo_rate = fields.Float(string='WooCommerce Rate (%)')
    odoo_tax_id = fields.Many2one('account.tax', string='Odoo Tax')

    @api.model
    def import_taxes_from_woo(self, instance):
        """Import tax rates from WooCommerce."""
        try:
            taxes = instance._api_get_all('taxes')
            for tax in taxes:
                existing = self.search([
                    ('woo_tax_rate_id', '=', str(tax.get('id'))),
                    ('instance_id', '=', instance.id),
                ], limit=1)
                vals = {
                    'name': tax.get('name', ''),
                    'woo_tax_rate_id': str(tax.get('id')),
                    'woo_tax_class': tax.get('class', ''),
                    'woo_rate': float(tax.get('rate', 0)),
                    'instance_id': instance.id,
                }
                if existing:
                    existing.write(vals)
                else:
                    self.create(vals)
        except Exception as e:
            instance._log('error', f'Tax import failed: {str(e)}')
