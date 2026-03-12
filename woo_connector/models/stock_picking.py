# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Override to trigger WooCommerce stock sync after validation."""
        result = super().button_validate()

        # Collect only the product.template IDs affected by this picking
        affected_tmpl_ids = self.mapped('move_ids.product_id.product_tmpl_id').ids
        if not affected_tmpl_ids:
            return result

        instances = self.env['woo.instance'].search([
            ('active', '=', True),
            ('state', '=', 'connected'),
            ('sync_stock', '=', True),
        ])
        for instance in instances:
            try:
                # Only sync the mappings for products in this picking
                mappings = self.env['woo.product.template'].sudo().search([
                    ('instance_id', '=', instance.id),
                    ('woo_id', '!=', False),
                    ('product_tmpl_id', 'in', affected_tmpl_ids),
                ])
                if mappings:
                    mappings._sync_stock_to_woo_for_mappings(instance)
            except Exception as e:
                _logger.warning(f'Post-picking WooCommerce stock sync failed: {str(e)}')
        return result