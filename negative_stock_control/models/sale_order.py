# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    has_negative_stock_warning = fields.Boolean(
        string='Has Negative Stock Warning',
        compute='_compute_negative_stock_warning',
        store=False)

    negative_stock_warning_message = fields.Text(
        string='Negative Stock Warning',
        compute='_compute_negative_stock_warning')

    def _compute_negative_stock_warning(self):
        """Check stock availability before confirmation."""
        for order in self:
            warnings = []
            for line in order.order_line:
                if line.product_id.type != 'consu':
                    continue
                product = line.product_id
                # Get stock from all warehouses
                qty_available = product.qty_available
                if qty_available < line.product_uom_qty:
                    shortfall = line.product_uom_qty - max(qty_available, 0)
                    warnings.append(
                        f"• {product.display_name}: "
                        f"Available={qty_available:.2f}, "
                        f"Ordered={line.product_uom_qty:.2f}, "
                        f"Shortfall={shortfall:.2f}"
                    )
            order.has_negative_stock_warning = bool(warnings)
            order.negative_stock_warning_message = '\n'.join(warnings) if warnings else ''

    def action_confirm(self):
        """Add soft-lock check before confirming sale order."""
        # Check if we should show warnings
        config = self.env['ir.config_parameter'].sudo()
        warn_on_so = config.get_param('negative_stock_control.warn_on_sale_order', 'True')
        if warn_on_so == 'True':
            for order in self:
                warnings = []
                for line in order.order_line:
                    if line.product_id.type != 'consu':
                        continue
                    product = line.product_id
                    qty_available = product.qty_available
                    if qty_available < line.product_uom_qty:
                        shortfall = line.product_uom_qty - max(qty_available, 0)
                        warnings.append(
                            f"• {product.display_name}: "
                            f"Available={qty_available:.2f}, "
                            f"Ordered={line.product_uom_qty:.2f}, "
                            f"Shortfall={shortfall:.2f}"
                        )
                if warnings:
                    wizard = self.env['sale.negative.stock.wizard'].create({
                        'sale_order_id': order.id,
                        'warning_message': '\n'.join(warnings),
                    })
                    return {
                        'type': 'ir.actions.act_window',
                        'name': _('⚠️ Stock Availability Warning'),
                        'res_model': 'sale.negative.stock.wizard',
                        'res_id': wizard.id,
                        'view_mode': 'form',
                        'target': 'new',
                    }
        return super().action_confirm()
