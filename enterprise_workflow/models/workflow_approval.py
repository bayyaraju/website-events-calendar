# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class WorkflowApproval(models.Model):
    """One approval request within a workflow instance approval stage."""
    _name = 'wf.approval'
    _description = 'Workflow Approval'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char(compute='_compute_name', store=True)

    instance_id  = fields.Many2one('wf.instance', required=True,
                                    ondelete='cascade', index=True)
    stage_id     = fields.Many2one('wf.stage',   ondelete='restrict')
    approver_id  = fields.Many2one('res.users',   required=True, index=True)
    delegate_id  = fields.Many2one('res.users',   'Delegate')

    state = fields.Selection([
        ('pending',   'Pending'),
        ('approved',  'Approved'),
        ('rejected',  'Rejected'),
        ('delegated', 'Delegated'),
        ('cancelled', 'Cancelled'),
    ], default='pending', required=True, tracking=True)

    comment      = fields.Text('Comment')
    responded_at = fields.Datetime('Responded', readonly=True)

    # ── Related display ───────────────────────────────────────────────────────
    definition_name = fields.Char(related='instance_id.definition_id.name', string='Workflow')
    res_model       = fields.Char(related='instance_id.res_model')
    res_id          = fields.Integer(related='instance_id.res_id', string='Res ID')
    res_name        = fields.Char(related='instance_id.res_name', string='Record')

    @api.depends('instance_id', 'stage_id', 'approver_id')
    def _compute_name(self):
        for r in self:
            r.name = ' | '.join(filter(None, [
                r.instance_id.name, r.stage_id.name, r.approver_id.name]))

    # ── Actions ───────────────────────────────────────────────────────────────
    def action_approve(self):
        for r in self:
            r._assert_can_respond()
            r.write({'state': 'approved', 'responded_at': fields.Datetime.now()})
            r.instance_id._log_event(
                'approval', f'Approved by {self.env.user.name} at stage {r.stage_id.name}')
            r.instance_id._check_approval_completion()

    def action_reject(self):
        for r in self:
            r._assert_can_respond()
            r.write({'state': 'rejected', 'responded_at': fields.Datetime.now()})
            r.instance_id._log_event(
                'approval', f'Rejected by {self.env.user.name} at stage {r.stage_id.name}')
            r.instance_id._check_approval_completion()

    def action_delegate(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Delegate Approval'),
            'res_model': 'wf.delegate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_approval_id': self.id},
        }

    def action_open_record(self):
        self.ensure_one()
        return self.instance_id.action_open_record()

    def _assert_can_respond(self):
        self.ensure_one()
        if self.state != 'pending':
            raise UserError(_('This approval is already %s.') % self.state)
        is_approver  = self.env.user == self.approver_id
        is_delegate  = self.env.user == self.delegate_id
        is_manager   = self.env.user.has_group('enterprise_workflow.group_wf_manager')
        if not (is_approver or is_delegate or is_manager):
            raise UserError(
                _('Only %s (or their delegate) can respond.') % self.approver_id.name)
