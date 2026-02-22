# -*- coding: utf-8 -*-
from odoo import fields, models


class WorkflowSLA(models.Model):
    """SLA rule attached to a workflow definition."""
    _name = 'wf.sla'
    _description = 'Workflow SLA Rule'
    _order = 'sequence, id'

    name     = fields.Char('Name', required=True)
    sequence = fields.Integer('Seq', default=10)
    active   = fields.Boolean(default=True)

    definition_id = fields.Many2one(
        'wf.definition', required=True, ondelete='cascade', index=True)

    sla_type = fields.Selection([
        ('total',    'Total Workflow Duration'),
        ('stage',    'Time in Stage'),
        ('approval', 'Approval Response Time'),
    ], default='total', required=True)

    stage_id = fields.Many2one(
        'wf.stage', 'Stage',
        domain="[('definition_id','=',definition_id)]")

    warning_hours = fields.Float('Warning (hours)', default=24.0)
    breach_hours  = fields.Float('Breach (hours)',  default=48.0)

    on_warning_action = fields.Selection([
        ('notify_owner',   'Notify Owner'),
        ('notify_manager', 'Notify Manager'),
        ('send_email',     'Send Email'),
    ], default='notify_owner')

    on_breach_action = fields.Selection([
        ('notify_owner',   'Notify Owner'),
        ('notify_manager', 'Notify Manager'),
        ('escalate',       'Escalate'),
        ('auto_advance',   'Auto-Advance'),
        ('abort',          'Abort'),
        ('send_email',     'Send Email'),
    ], default='escalate')

    email_template_id = fields.Many2one('mail.template', 'Email Template')

    notify_user_ids = fields.Many2many(
        'res.users',  'wf_sla_notify_user_rel',  'sla_id', 'user_id',  'Notify Users')
    notify_group_ids = fields.Many2many(
        'res.groups', 'wf_sla_notify_group_rel', 'sla_id', 'group_id', 'Notify Groups')

    use_biz_hours       = fields.Boolean('Business Hours Only', default=False)
    biz_hours_start     = fields.Float('Start (h)', default=9.0)
    biz_hours_end       = fields.Float('End (h)',   default=18.0)
