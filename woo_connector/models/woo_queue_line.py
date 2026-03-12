# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class WooQueueLine(models.Model):
    _name = 'woo.queue.line'
    _description = 'WooCommerce Sync Queue'
    _order = 'create_date desc'

    instance_id = fields.Many2one('woo.instance', string='Instance', required=True, ondelete='cascade')
    name = fields.Char(string='Reference')
    queue_type = fields.Selection([
        ('order', 'Order'),
        ('product', 'Product'),
        ('stock', 'Stock'),
        ('customer', 'Customer'),
        ('refund', 'Refund'),
    ], string='Type', required=True)
    state = fields.Selection([
        ('draft', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], default='draft', string='State')
    woo_id = fields.Integer(string='WooCommerce ID')
    data = fields.Text(string='Payload (JSON)')
    error_message = fields.Text(string='Error')
    retry_count = fields.Integer(string='Retry Count', default=0)
    processed_date = fields.Datetime(string='Processed Date')

    def action_process(self):
        """Process this queue item."""
        self.ensure_one()
        self.state = 'processing'
        try:
            data = json.loads(self.data or '{}')
            if self.queue_type == 'order':
                self.env['sale.order'].sudo()._process_woo_order(self.instance_id, data)
            elif self.queue_type == 'product':
                self.env['woo.product.template'].sudo()._process_woo_product(self.instance_id, data)
            elif self.queue_type == 'stock':
                self.env['woo.product.template'].sudo().sync_stock_to_woo(self.instance_id)
            elif self.queue_type == 'customer':
                self.env['res.partner'].sudo()._process_woo_customer(self.instance_id, data)

            self.write({
                'state': 'done',
                'processed_date': fields.Datetime.now(),
                'error_message': False,
            })
        except Exception as e:
            self.write({
                'state': 'failed',
                'retry_count': self.retry_count + 1,
                'error_message': str(e),
            })
            _logger.error(f'Queue line {self.id} failed: {str(e)}')

    def action_reset(self):
        """Reset failed queue lines to draft."""
        self.filtered(lambda q: q.state == 'failed').write({
            'state': 'draft',
            'error_message': False,
        })

    def action_cancel(self):
        self.write({'state': 'failed'})
