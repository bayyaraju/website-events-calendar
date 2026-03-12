# -*- coding: utf-8 -*-
from odoo import api, fields, models


class WooLog(models.Model):
    _name = 'woo.log'
    _description = 'WooCommerce Sync Log'
    _order = 'create_date desc'
    _rec_name = 'message'

    instance_id = fields.Many2one('woo.instance', string='Instance', ondelete='cascade')
    level = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('success', 'Success'),
    ], default='info', string='Level')
    message = fields.Text(string='Message', required=True)
    model = fields.Char(string='Model')
    res_id = fields.Integer(string='Record ID')
    create_date = fields.Datetime(string='Date', readonly=True)

    @api.model
    def clean_old_logs(self, days=30):
        """Auto-clean logs older than N days."""
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        old_logs = self.search([('create_date', '<', cutoff)])
        old_logs.unlink()
