# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    negative_stock_setting = fields.Selection([
        ('inherit', 'Inherit from Category / Warehouse'),
        ('allow', 'Always Allow Negative'),
        ('block', 'Always Block Negative (Strict)'),
    ], string='Negative Stock Control',
        default='inherit',
        help='Product-level override for negative stock policy.\n'
             '- Inherit: uses category or warehouse setting\n'
             '- Allow: product can always go negative\n'
             '- Block: product is always strictly blocked')

    negative_stock_note = fields.Char(
        string='Reason / Note',
        help='Optional note explaining the negative stock setting (e.g., "Service product, no physical stock")')

    # Computed effective policy shown on product form
    effective_negative_policy = fields.Char(
        string='Effective Policy',
        compute='_compute_effective_policy',
        help='Shows the currently active policy considering all inheritance levels.')

    def _compute_effective_policy(self):
        for product in self:
            if product.negative_stock_setting == 'allow':
                product.effective_negative_policy = '🟢 Always Allow'
            elif product.negative_stock_setting == 'block':
                product.effective_negative_policy = '🔴 Always Block (Strict)'
            else:
                cat = product.categ_id
                if cat.negative_stock_setting == 'allow':
                    product.effective_negative_policy = '🟢 Allow (from Category)'
                elif cat.negative_stock_setting == 'block':
                    product.effective_negative_policy = '🔴 Block (from Category)'
                else:
                    product.effective_negative_policy = '🏭 Warehouse Policy'
