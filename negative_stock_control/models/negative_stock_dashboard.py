# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta


class NegativeStockDashboard(models.Model):
    """
    Virtual model populated by the cron / on-demand refresh.
    Stores a snapshot of products currently at negative stock.
    """
    _name = 'negative.stock.dashboard'
    _description = 'Negative Stock Dashboard'
    _order = 'qty_on_hand asc'
    _rec_name = 'product_id'

    product_id = fields.Many2one('product.product', string='Product', required=True, index=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', index=True)
    location_id = fields.Many2one('stock.location', string='Location')
    company_id = fields.Many2one('res.company', string='Company',
                                  default=lambda self: self.env.company)
    qty_on_hand = fields.Float(string='On Hand Qty', digits='Product Unit of Measure')
    qty_reserved = fields.Float(string='Reserved Qty', digits='Product Unit of Measure')
    qty_available = fields.Float(string='Available Qty', digits='Product Unit of Measure')
    qty_incoming = fields.Float(string='Incoming Qty', digits='Product Unit of Measure')
    qty_forecasted = fields.Float(string='Forecasted Qty', digits='Product Unit of Measure')
    negative_since = fields.Datetime(string='Negative Since')
    days_negative = fields.Integer(string='Days Negative', compute='_compute_days_negative', store=True)
    responsible_user_id = fields.Many2one('res.users', string='Responsible',
                                           related='product_id.product_tmpl_id.responsible_id',
                                           store=True)
    last_override_user_id = fields.Many2one('res.users', string='Last Override By',
                                             compute='_compute_last_override')
    override_count = fields.Integer(string='Override Count', compute='_compute_last_override')
    state = fields.Selection([
        ('critical', 'Critical'),
        ('warning', 'Warning'),
        ('info', 'Info'),
    ], string='Severity', compute='_compute_state', store=True)

    @api.depends('negative_since')
    def _compute_days_negative(self):
        now = datetime.now()
        for rec in self:
            if rec.negative_since:
                rec.days_negative = (now - rec.negative_since).days
            else:
                rec.days_negative = 0

    @api.depends('days_negative', 'qty_on_hand')
    def _compute_state(self):
        for rec in self:
            if rec.days_negative >= 7 or rec.qty_on_hand < -100:
                rec.state = 'critical'
            elif rec.days_negative >= 3 or rec.qty_on_hand < -10:
                rec.state = 'warning'
            else:
                rec.state = 'info'

    def _compute_last_override(self):
        for rec in self:
            logs = self.env['negative.stock.log'].search([
                ('product_id', '=', rec.product_id.id),
                ('location_id', '=', rec.location_id.id),
            ], order='override_date desc', limit=1)
            if logs:
                rec.last_override_user_id = logs.user_id
                all_logs = self.env['negative.stock.log'].search_count([
                    ('product_id', '=', rec.product_id.id),
                    ('location_id', '=', rec.location_id.id),
                ])
                rec.override_count = all_logs
            else:
                rec.last_override_user_id = False
                rec.override_count = 0

    @api.model
    def refresh_dashboard(self):
        """Called by cron or manually to refresh the dashboard data."""
        company = self.env.company
        # Remove stale records for this company
        self.search([('company_id', '=', company.id)]).unlink()

        quants = self.env['stock.quant'].search([
            ('quantity', '<', 0),
            ('location_id.usage', '=', 'internal'),
            ('company_id', '=', company.id),
        ])

        for quant in quants:
            # Find warehouse from location
            warehouse = self._get_warehouse_from_location(quant.location_id)
            product = quant.product_id

            # Find when it first went negative (earliest log or now)
            earliest_log = self.env['negative.stock.log'].search([
                ('product_id', '=', product.id),
                ('location_id', 'child_of', quant.location_id.id),
            ], order='override_date asc', limit=1)
            negative_since = earliest_log.override_date if earliest_log else fields.Datetime.now()

            # Compute forecasted qty
            forecasted = product.with_context(
                location=quant.location_id.id
            ).virtual_available

            self.create({
                'product_id': product.id,
                'warehouse_id': warehouse.id if warehouse else False,
                'location_id': quant.location_id.id,
                'company_id': company.id,
                'qty_on_hand': quant.quantity,
                'qty_reserved': quant.reserved_quantity,
                'qty_available': quant.quantity - quant.reserved_quantity,
                'qty_forecasted': forecasted,
                'negative_since': negative_since,
            })
        return True

    def _get_warehouse_from_location(self, location):
        """Walk up location hierarchy to find the warehouse."""
        warehouses = self.env['stock.warehouse'].search([
            ('company_id', '=', self.env.company.id)
        ])
        for wh in warehouses:
            if location.id == wh.lot_stock_id.id or \
               location.location_id.id == wh.lot_stock_id.id or \
               location._location_belongs_to_warehouse(wh):
                return wh
        return self.env['stock.warehouse'].browse()

    def action_view_product(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.product_id.name,
            'res_model': 'product.product',
            'res_id': self.product_id.id,
            'view_mode': 'form',
        }

    def action_view_overrides(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Override History',
            'res_model': 'negative.stock.log',
            'view_mode': 'list,form',
            'domain': [('product_id', '=', self.product_id.id)],
        }
