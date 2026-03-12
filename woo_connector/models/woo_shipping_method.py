# -*- coding: utf-8 -*-
from odoo import api, fields, models


class WooShippingMethod(models.Model):
    _name = 'woo.shipping.method'
    _description = 'WooCommerce Shipping Method'

    instance_id = fields.Many2one('woo.instance', string='Instance', required=True, ondelete='cascade')
    name = fields.Char(string='WooCommerce Method', required=True)
    woo_method_id = fields.Char(string='WooCommerce Method ID')
    woo_instance_id_ref = fields.Char(string='WooCommerce Instance ID')
    odoo_delivery_id = fields.Many2one('delivery.carrier', string='Odoo Delivery Carrier')
