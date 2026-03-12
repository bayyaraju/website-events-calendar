# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    sync_to_woo = fields.Boolean(string='Sync to WooCommerce', default=True)
    woo_product_ids = fields.One2many(
        'woo.product.template', 'product_tmpl_id', string='WooCommerce Products'
    )

    def action_push_to_woo(self):
        """Manually push product to all connected WooCommerce instances."""
        instances = self.env['woo.instance'].search([
            ('active', '=', True), ('state', '=', 'connected')
        ])
        for instance in instances:
            self.env['woo.product.template'].sudo()._push_product_to_woo(instance, self)
