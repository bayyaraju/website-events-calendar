# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductCategory(models.Model):
    _inherit = 'product.category'

    negative_stock_setting = fields.Selection([
        ('inherit', 'Inherit from Warehouse'),
        ('allow', 'Always Allow Negative'),
        ('block', 'Always Block Negative'),
    ], string='Negative Stock Setting',
        default='inherit',
        help='Override warehouse-level policy for all products in this category.')
