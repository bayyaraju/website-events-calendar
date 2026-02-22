# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SaleNegativeStockWizard(models.TransientModel):
    _name = 'sale.negative.stock.wizard'
    _description = 'Sale Order Negative Stock Warning'

    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True)
    warning_message = fields.Text(string='Stock Issues', readonly=True)

    def action_confirm_anyway(self):
        """Proceed with confirming despite stock warning."""
        self.ensure_one()
        # Post warning to chatter
        self.sale_order_id.message_post(
            body=_(
                "<b>⚠️ Sale Order confirmed with insufficient stock</b><br/>"
                "<pre>%s</pre><br/>Confirmed by: %s"
            ) % (self.warning_message, self.env.user.name),
            subject=_('Low Stock Warning on SO Confirmation'),
        )
        return self.sale_order_id.with_context(skip_negative_stock_warning=True).action_confirm()

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
