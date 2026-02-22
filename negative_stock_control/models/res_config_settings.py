# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Global default policy
    negative_stock_default_policy = fields.Selection([
        ('allow', '🟢 Allow (No Restriction)'),
        ('warn', '🟡 Warn Only'),
        ('block', '🔴 Strict Block'),
    ], string='Default Negative Stock Policy',
        config_parameter='negative_stock_control.default_policy',
        default='warn')

    negative_stock_warn_on_sale_order = fields.Boolean(
        string='Warn on Sale Order Confirmation',
        config_parameter='negative_stock_control.warn_on_sale_order',
        default=True)

    negative_stock_cron_email = fields.Boolean(
        string='Send Daily Alert Email',
        config_parameter='negative_stock_control.cron_email',
        default=True)

    negative_stock_admin_email = fields.Char(
        string='Alert Email Address',
        config_parameter='negative_stock_control.admin_email')

    negative_stock_analytics_days = fields.Integer(
        string='Analytics Lookback (Days)',
        config_parameter='negative_stock_control.analytics_days',
        default=30)
