# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class WfDelegateWizard(models.TransientModel):
    """Delegate an approval to another user."""
    _name = 'wf.delegate.wizard'
    _description = 'Delegate Approval'

    approval_id  = fields.Many2one('wf.approval', readonly=True)
    delegate_to  = fields.Many2one('res.users', required=True,
                                    domain=[('share', '=', False)])
    reason       = fields.Text('Reason')

    def action_delegate(self):
        self.ensure_one()
        appr = self.approval_id
        if appr.state != 'pending':
            raise UserError(_('Approval is no longer pending.'))
        appr.write({'state': 'delegated', 'delegate_id': self.delegate_to.id,
                    'comment': self.reason})
        self.env['wf.approval'].create({
            'instance_id': appr.instance_id.id,
            'stage_id':    appr.stage_id.id,
            'approver_id': self.delegate_to.id,
            'state':       'pending',
        })
        appr.instance_id._log_event(
            'approval',
            f'Delegated from {appr.approver_id.name} to {self.delegate_to.name}')
        return {'type': 'ir.actions.act_window_close'}
