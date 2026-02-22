# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class StockOverrideWizardLine(models.TransientModel):
    _name = 'stock.override.wizard.line'
    _description = 'Stock Override Wizard Line'

    wizard_id = fields.Many2one('stock.override.wizard', string='Wizard')
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    location_id = fields.Many2one('stock.location', string='Location', readonly=True)
    qty_available = fields.Float(string='Available Qty', readonly=True)
    qty_requested = fields.Float(string='Requested Qty', readonly=True)
    qty_shortfall = fields.Float(string='Shortfall', readonly=True)
    policy = fields.Selection([
        ('warn', 'Warning'),
        ('block', 'Blocked'),
    ], string='Policy', readonly=True)
    move_id = fields.Many2one('stock.move', string='Move', readonly=True)


class StockOverrideWizard(models.TransientModel):
    _name = 'stock.override.wizard'
    _description = 'Negative Stock Override Wizard'

    picking_id = fields.Many2one('stock.picking', string='Transfer', readonly=True)
    warn_only = fields.Boolean(string='Warning Only Mode', readonly=True)
    line_ids = fields.One2many('stock.override.wizard.line', 'wizard_id', string='Issues')
    reason = fields.Text(string='Override Reason',
                          help='Mandatory: Explain why you are proceeding with negative stock.')

    override_count_total = fields.Integer(
        string='Total Overrides',
        compute='_compute_override_stats')
    override_count_user = fields.Integer(
        string='Your Overrides (30d)',
        compute='_compute_override_stats')

    def _compute_override_stats(self):
        for wiz in self:
            stats = self.env['negative.stock.log']._get_override_stats(days=30)
            wiz.override_count_total = stats['total_overrides']
            user_logs = self.env['negative.stock.log'].search_count([
                ('user_id', '=', self.env.user.id),
            ])
            wiz.override_count_user = user_logs

    @api.constrains('reason')
    def _check_reason(self):
        for wiz in self:
            if not wiz.warn_only:
                warehouse = wiz.picking_id and wiz.picking_id.move_ids[:1] and \
                            wiz.picking_id.move_ids[:1]._get_warehouse_from_location(
                                wiz.picking_id.move_ids[:1].location_id)
                if warehouse and warehouse.override_requires_reason:
                    if not wiz.reason or len(wiz.reason.strip()) < 5:
                        raise ValidationError(
                            _('You must provide a valid reason (at least 5 characters) '
                              'to override the negative stock block.'))

    def action_proceed(self):
        """User confirms they want to proceed despite negative stock."""
        self.ensure_one()
        reason = self.reason or _('No reason provided')

        # Mark moves as overridden
        for line in self.line_ids:
            move = line.move_id
            if move:
                move.write({
                    'negative_stock_overridden': True,
                    'negative_stock_override_reason': reason,
                    'negative_stock_override_user': self.env.user.id,
                })
                # Log the override
                override_type = 'warn_accepted' if self.warn_only else 'override'
                self.picking_id._log_negative_stock_override(move, reason, override_type)

        # Now validate the picking
        return self.picking_id.with_context(bypass_negative_check=True).button_validate()

    def action_cancel(self):
        """User cancels – do not proceed."""
        return {'type': 'ir.actions.act_window_close'}
