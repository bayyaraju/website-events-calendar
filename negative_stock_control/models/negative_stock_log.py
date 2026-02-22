# -*- coding: utf-8 -*-
from odoo import models, fields, api


class NegativeStockLog(models.Model):
    _name = 'negative.stock.log'
    _description = 'Negative Stock Override Log'
    _order = 'create_date desc'
    _rec_name = 'product_id'

    product_id = fields.Many2one('product.product', string='Product', required=True, index=True)
    location_id = fields.Many2one('stock.location', string='Location', required=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    user_id = fields.Many2one('res.users', string='Override By', required=True,
                               default=lambda self: self.env.user)
    company_id = fields.Many2one('res.company', string='Company',
                                  default=lambda self: self.env.company)
    override_date = fields.Datetime(string='Override Date', default=fields.Datetime.now)
    quantity_requested = fields.Float(string='Quantity Requested', digits='Product Unit of Measure')
    quantity_on_hand = fields.Float(string='Qty On Hand at Override', digits='Product Unit of Measure')
    quantity_after = fields.Float(string='Qty After Operation', digits='Product Unit of Measure')
    reason = fields.Text(string='Override Reason', required=True)
    picking_id = fields.Many2one('stock.picking', string='Transfer Reference')
    sale_order_id = fields.Many2one('sale.order', string='Sale Order Reference')
    override_type = fields.Selection([
        ('override', 'Manager Override'),
        ('warn_accepted', 'Warning Accepted'),
    ], string='Override Type', default='override')

    @api.model
    def _get_override_stats(self, days=30):
        """Return analytics data for the last N days."""
        from datetime import datetime, timedelta
        since = datetime.now() - timedelta(days=days)
        domain = [('override_date', '>=', since), ('company_id', '=', self.env.company.id)]
        logs = self.search(domain)
        user_counts = {}
        product_counts = {}
        for log in logs:
            user_counts[log.user_id.name] = user_counts.get(log.user_id.name, 0) + 1
            product_counts[log.product_id.name] = product_counts.get(log.product_id.name, 0) + 1
        return {
            'total_overrides': len(logs),
            'top_users': sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:5],
            'top_products': sorted(product_counts.items(), key=lambda x: x[1], reverse=True)[:5],
        }
