# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class StockMove(models.Model):
    _inherit = 'stock.move'

    negative_stock_overridden = fields.Boolean(
        string='Negative Stock Overridden', default=False, copy=False)
    negative_stock_override_reason = fields.Text(
        string='Override Reason', copy=False)
    negative_stock_override_user = fields.Many2one(
        'res.users', string='Override By', copy=False)

    def _get_product_effective_policy(self, product, location):
        """
        Determine effective negative stock policy for a product/location combination.
        Priority: Product > Category > Warehouse > Global
        Returns: 'allow', 'warn', 'block'
        """
        tmpl = product.product_tmpl_id

        # Product-level override
        if tmpl.negative_stock_setting == 'allow':
            return 'allow'
        if tmpl.negative_stock_setting == 'block':
            return 'block'

        # Category-level
        cat = tmpl.categ_id
        if cat.negative_stock_setting == 'allow':
            return 'allow'
        if cat.negative_stock_setting == 'block':
            return 'block'

        # Warehouse-level
        warehouse = self._get_warehouse_from_location(location)
        if warehouse:
            return warehouse.negative_stock_policy

        # Global default from settings
        return self.env['ir.config_parameter'].sudo().get_param(
            'negative_stock_control.default_policy', 'warn')

    def _get_warehouse_from_location(self, location):
        """Find the warehouse that owns this location."""
        warehouses = self.env['stock.warehouse'].search([
            ('company_id', '=', self.env.company.id)
        ])
        for wh in warehouses:
            if location._location_belongs_to_warehouse(wh):
                return wh
        return None

    def _compute_available_quantity(self, product, location, warehouse=None):
        """
        Compute available quantity based on warehouse calculation method.
        """
        method = 'available'
        if warehouse:
            method = warehouse.stock_calculation_method

        quant = self.env['stock.quant'].sudo()._gather(product, location)
        qty_on_hand = sum(quant.mapped('quantity'))
        qty_reserved = sum(quant.mapped('reserved_quantity'))

        if method == 'on_hand':
            return qty_on_hand
        elif method == 'available':
            return qty_on_hand - qty_reserved
        elif method == 'forecasted':
            return product.with_context(location=location.id).virtual_available
        return qty_on_hand - qty_reserved

    def _check_negative_stock(self):
        """
        Main method called before validating moves.
        Returns list of (move, policy, available_qty) for moves that would cause negative stock.
        """
        issues = []
        for move in self:
            if move.state in ('done', 'cancel'):
                continue
            if not move.location_id or move.location_id.usage != 'internal':
                continue
            if move.negative_stock_overridden:
                continue

            product = move.product_id
            location = move.location_id
            warehouse = self._get_warehouse_from_location(location)
            policy = self._get_product_effective_policy(product, location)

            if policy == 'allow':
                continue

            available = self._compute_available_quantity(product, location, warehouse)
            demand = move.product_uom_qty

            if available - demand < 0:
                issues.append({
                    'move': move,
                    'policy': policy,
                    'available': available,
                    'demand': demand,
                    'shortfall': demand - available,
                    'warehouse': warehouse,
                    'product': product,
                    'location': location,
                })
        return issues

    def _action_confirm(self, merge=True, merge_into=False):
        return super()._action_confirm(merge=merge, merge_into=merge_into)

    def _action_assign(self):
        return super()._action_assign()

    def write(self, vals):
        return super().write(vals)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    has_negative_override = fields.Boolean(
        string='Has Override',
        compute='_compute_has_negative_override', store=True)

    @api.depends('move_ids.negative_stock_overridden')
    def _compute_has_negative_override(self):
        for picking in self:
            picking.has_negative_override = any(
                m.negative_stock_overridden for m in picking.move_ids)

    def button_validate(self):
        """Override validate to inject negative stock check."""
        issues = self.move_ids._check_negative_stock()
        if not issues:
            return super().button_validate()

        # Categorize by policy
        block_issues = [i for i in issues if i['policy'] == 'block']
        warn_issues = [i for i in issues if i['policy'] == 'warn']

        # Check if manager override is possible
        is_manager = self.env.user.has_group('stock.group_stock_manager')

        if block_issues:
            warehouse = block_issues[0]['warehouse']
            allow_override = warehouse and warehouse.allow_manager_override and is_manager
            if not allow_override:
                # Hard block
                lines = []
                for issue in block_issues:
                    lines.append(
                        f"• {issue['product'].display_name}: "
                        f"Available={issue['available']:.2f}, "
                        f"Requested={issue['demand']:.2f}, "
                        f"Shortfall={issue['shortfall']:.2f}"
                    )
                raise UserError(
                    _("🔴 NEGATIVE STOCK BLOCKED\n\n"
                      "The following products would go negative and are strictly blocked:\n\n%s\n\n"
                      "Please adjust quantities or contact your Inventory Manager.")
                    % '\n'.join(lines)
                )
            else:
                # Manager can override – open wizard
                all_issues = block_issues + warn_issues
                return self._open_override_wizard(all_issues)

        if warn_issues:
            return self._open_override_wizard(warn_issues, warn_only=True)

        return super().button_validate()

    def _open_override_wizard(self, issues, warn_only=False):
        """Open the override wizard with issue context."""
        self.ensure_one()
        # Serialize issue data to pass to wizard
        issue_lines = []
        for issue in issues:
            issue_lines.append((0, 0, {
                'product_id': issue['product'].id,
                'location_id': issue['location'].id,
                'qty_available': issue['available'],
                'qty_requested': issue['demand'],
                'qty_shortfall': issue['shortfall'],
                'policy': issue['policy'],
                'move_id': issue['move'].id,
            }))

        wizard = self.env['stock.override.wizard'].create({
            'picking_id': self.id,
            'warn_only': warn_only,
            'line_ids': issue_lines,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('⚠️ Negative Stock Warning') if warn_only else _('🔴 Override Required'),
            'res_model': 'stock.override.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _log_negative_stock_override(self, move, reason, override_type='override'):
        """Write override log and post to chatter."""
        log = self.env['negative.stock.log'].create({
            'product_id': move.product_id.id,
            'location_id': move.location_id.id,
            'warehouse_id': self._get_warehouse_id(move.location_id),
            'user_id': self.env.user.id,
            'quantity_requested': move.product_uom_qty,
            'quantity_on_hand': sum(
                self.env['stock.quant'].sudo()._gather(
                    move.product_id, move.location_id).mapped('quantity')),
            'quantity_after': sum(
                self.env['stock.quant'].sudo()._gather(
                    move.product_id, move.location_id).mapped('quantity')) - move.product_uom_qty,
            'reason': reason,
            'picking_id': self.id,
            'override_type': override_type,
        })
        self.message_post(
            body=_(
                "<b>⚠️ Negative Stock Override</b><br/>"
                "Product: <b>%s</b><br/>"
                "Location: %s<br/>"
                "Qty Requested: %.2f<br/>"
                "Override Reason: %s<br/>"
                "By: %s"
            ) % (
                move.product_id.display_name,
                move.location_id.display_name,
                move.product_uom_qty,
                reason,
                self.env.user.name,
            ),
            subject=_('Negative Stock Override'),
        )
        return log

    def _get_warehouse_id(self, location):
        warehouses = self.env['stock.warehouse'].search([
            ('company_id', '=', self.env.company.id)
        ])
        for wh in warehouses:
            if location._location_belongs_to_warehouse(wh):
                return wh.id
        return False


class StockLocation(models.Model):
    _inherit = 'stock.location'

    def _location_belongs_to_warehouse(self, warehouse):
        """Check if this location belongs to the given warehouse."""
        return self.id in (
            warehouse.lot_stock_id | warehouse.wh_input_stock_loc_id |
            warehouse.wh_output_stock_loc_id | warehouse.wh_pack_stock_loc_id
        ).ids or self.location_id and self.location_id._location_belongs_to_warehouse(warehouse) \
            if self.location_id else False
