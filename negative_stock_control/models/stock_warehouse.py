# -*- coding: utf-8 -*-
from odoo import models, fields, api


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    # ── Negative Stock Policy ──────────────────────────────────────────────
    negative_stock_policy = fields.Selection([
        ('allow', '🟢 Allow (No Restriction)'),
        ('warn', '🟡 Warn Only (Popup but Allow)'),
        ('block', '🔴 Strict Block (Hard Stop)'),
    ], string='Negative Stock Policy', default='warn',
        help='Controls how the system reacts when stock would go negative.')

    allow_manager_override = fields.Boolean(
        string='Allow Manager Override',
        default=True,
        help='Allow users with Stock Manager role to override strict blocks.')

    override_requires_reason = fields.Boolean(
        string='Require Reason for Override',
        default=True,
        help='Force users to enter a reason when overriding a block.')

    # ── Stock Calculation Method ───────────────────────────────────────────
    stock_calculation_method = fields.Selection([
        ('on_hand', 'On Hand Only'),
        ('available', 'On Hand – Reserved (Available)'),
        ('forecasted', 'Forecasted Quantity'),
    ], string='Stock Calculation Method', default='available',
        help='Determines what quantity is checked against zero.')

    # ── Forecast Consideration ─────────────────────────────────────────────
    consider_incoming = fields.Boolean(
        string='Consider Incoming Shipments',
        default=False,
        help='Include incoming shipments in stock calculation.')

    consider_manufacturing = fields.Boolean(
        string='Consider Manufacturing Orders',
        default=False,
        help='Include manufacturing orders in stock calculation.')

    # ── Alert Settings ─────────────────────────────────────────────────────
    alert_email_ids = fields.Many2many(
        'res.users',
        'warehouse_alert_user_rel',
        'warehouse_id',
        'user_id',
        string='Alert Recipients',
        help='Users who receive negative stock email alerts for this warehouse.')

    negative_count = fields.Integer(
        string='Negative Products Count',
        compute='_compute_negative_count')

    def _compute_negative_count(self):
        for wh in self:
            location = wh.lot_stock_id
            quants = self.env['stock.quant'].search([
                ('location_id', 'child_of', location.id),
                ('quantity', '<', 0),
            ])
            wh.negative_count = len(quants.mapped('product_id'))

    def action_view_negative_stock(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Negative Stock Products',
            'res_model': 'negative.stock.dashboard',
            'view_mode': 'list,form',
            'domain': [('warehouse_id', '=', self.id), ('qty_on_hand', '<', 0)],
            'context': {'default_warehouse_id': self.id},
        }
