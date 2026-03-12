# -*- coding: utf-8 -*-
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class WooMixin(models.AbstractModel):
    """Shared helpers for all WooCommerce connector models."""
    _name = 'woo.mixin'
    _description = 'WooCommerce Mixin'

    def _safe_product_type_vals(self, instance, base_vals):
        """
        Return base_vals dict with the correct type field set for the running
        Odoo version.

        - Odoo 17:        field = 'detailed_type', values = 'product'/'consu'/'service'
        - Odoo 16/18/19:  field = 'type',           values = 'consu'/'service' (base)
                          + 'product' added by the stock module via selection_add

        We detect valid values at runtime so the code works on every version
        without modification.
        """
        product_tmpl_fields = self.env['product.template'].fields_get(
            ['type', 'detailed_type']
        )

        if 'detailed_type' in product_tmpl_fields:
            type_field = 'detailed_type'
        else:
            type_field = 'type'

        desired = instance.default_product_type  # 'product', 'consu', or 'service'
        valid_values = [
            v[0] for v in product_tmpl_fields.get(type_field, {}).get('selection', [])
        ]

        if valid_values and desired not in valid_values:
            fallback = 'consu' if 'consu' in valid_values else (valid_values[0] if valid_values else 'consu')
            _logger.warning(
                "[WooConnector] Product type '%s' is not valid on this Odoo instance "
                "(valid: %s). Falling back to '%s'. "
                "Check Configuration → Instance → Product Settings.",
                desired, valid_values, fallback
            )
            desired = fallback

        return dict(base_vals, **{type_field: desired})
