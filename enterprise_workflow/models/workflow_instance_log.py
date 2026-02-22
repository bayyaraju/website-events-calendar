# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class WorkflowInstanceLog(models.Model):
    """Immutable audit trail for every workflow event."""
    _name = 'wf.instance.log'
    _description = 'Workflow Instance Log'
    _order = 'create_date desc, id desc'
    _log_access = True

    instance_id = fields.Many2one(
        'wf.instance', required=True, ondelete='cascade', index=True)

    log_type = fields.Selection([
        ('stage_entry', 'Stage Entry'),
        ('transition',  'Transition'),
        ('action',      'Action'),
        ('approval',    'Approval'),
        ('sla_breach',  'SLA Breach'),
        ('error',       'Error'),
        ('info',        'Info'),
        ('completed',   'Completed'),
        ('cancelled',   'Cancelled'),
    ], required=True, default='info')

    message      = fields.Text('Message',  required=True)
    comment      = fields.Text('Comment')
    user_id      = fields.Many2one('res.users', 'User', default=lambda s: s.env.user)

    stage_id     = fields.Many2one('wf.stage',      'Stage',      ondelete='set null')
    from_stage_id = fields.Many2one('wf.stage',     'From Stage', ondelete='set null')
    to_stage_id  = fields.Many2one('wf.stage',      'To Stage',   ondelete='set null')
    transition_id = fields.Many2one('wf.transition', 'Transition', ondelete='set null')

    # ── Immutability ──────────────────────────────────────────────────────────
    def write(self, vals):
        raise UserError('Workflow logs are immutable.')

    def unlink(self):
        raise UserError('Workflow logs cannot be deleted.')
