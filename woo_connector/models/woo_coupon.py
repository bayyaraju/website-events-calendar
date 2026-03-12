# -*- coding: utf-8 -*-
from odoo import api, fields, models


class WooCoupon(models.Model):
    _name = 'woo.coupon'
    _description = 'WooCommerce Coupon'

    instance_id = fields.Many2one('woo.instance', string='Instance', required=True, ondelete='cascade')
    name = fields.Char(string='Coupon Code', required=True)
    woo_id = fields.Integer(string='WooCommerce ID')
    discount_type = fields.Selection([
        ('percent', 'Percentage'),
        ('fixed_cart', 'Fixed Cart'),
        ('fixed_product', 'Fixed Product'),
    ], string='Discount Type')
    amount = fields.Float(string='Amount')
    expiry_date = fields.Date(string='Expiry Date')
    usage_count = fields.Integer(string='Usage Count')
    usage_limit = fields.Integer(string='Usage Limit')

    @api.model
    def import_coupons_from_woo(self, instance):
        """Import coupons from WooCommerce."""
        try:
            coupons = instance._api_get_all('coupons')
            for coupon in coupons:
                existing = self.search([
                    ('woo_id', '=', coupon.get('id')),
                    ('instance_id', '=', instance.id),
                ], limit=1)
                vals = {
                    'name': coupon.get('code', ''),
                    'woo_id': coupon.get('id'),
                    'instance_id': instance.id,
                    'discount_type': coupon.get('discount_type', 'percent'),
                    'amount': float(coupon.get('amount', 0)),
                    'usage_count': coupon.get('usage_count', 0),
                    'usage_limit': coupon.get('usage_limit') or 0,
                }
                if coupon.get('date_expires'):
                    from datetime import datetime
                    try:
                        vals['expiry_date'] = datetime.fromisoformat(
                            coupon['date_expires'].replace('Z', '+00:00')
                        ).date()
                    except Exception:
                        pass
                if existing:
                    existing.write(vals)
                else:
                    self.create(vals)
        except Exception as e:
            instance._log('error', f'Coupon import failed: {str(e)}')
