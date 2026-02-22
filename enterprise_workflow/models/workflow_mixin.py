# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class WorkflowMixin(models.AbstractModel):
    """
    AbstractModel mixin — inherit to add workflow controls to any model.

    Usage:
        class SaleOrder(models.Model):
            _inherit = ['sale.order', 'workflow.mixin']
    """
    _name = 'workflow.mixin'
    _description = 'Workflow Mixin'

    wf_instance_ids = fields.One2many(
        'wf.instance', 'res_id',
        string='Workflow Instances IDS',
        domain=lambda self: [('res_model', '=', self._name)])

    wf_instance_count = fields.Integer(
        compute='_compute_wf_count', string='Workflows')

    wf_active_stage = fields.Char(
        compute='_compute_wf_active', string='Active Stage')

    wf_active_state = fields.Char(
        compute='_compute_wf_active', string='Workflow State')

    @api.depends('wf_instance_ids')
    def _compute_wf_count(self):
        for r in self:
            r.wf_instance_count = len(r.wf_instance_ids)

    @api.depends('wf_instance_ids.state', 'wf_instance_ids.current_stage_name')
    def _compute_wf_active(self):
        for r in self:
            active = r.wf_instance_ids.filtered(
                lambda i: i.state in ('running', 'waiting', 'pending_approval'))
            if active:
                r.wf_active_stage = active[0].current_stage_name
                r.wf_active_state = active[0].state
            else:
                r.wf_active_stage = False
                r.wf_active_state = False

    def action_start_workflow(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Start Workflow'),
            'res_model': 'wf.trigger.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id':    self.id,
                'default_res_name':  self.display_name,
            },
        }

    def action_view_workflows(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Workflow Instances'),
            'res_model': 'wf.instance',
            'view_mode': 'list,form',
            'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
        }
