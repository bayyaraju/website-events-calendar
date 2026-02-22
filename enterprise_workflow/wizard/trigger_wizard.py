# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class WfTriggerWizard(models.TransientModel):
    """Wizard to manually start a workflow on a record."""
    _name = 'wf.trigger.wizard'
    _description = 'Start Workflow'

    res_model = fields.Char('Model',   readonly=True)
    res_id    = fields.Integer('Res ID',   readonly=True)
    res_name  = fields.Char('Record',  readonly=True)

    definition_id = fields.Many2one(
        'wf.definition', 'Workflow', required=True,
        domain="[('state','=','active'),('model_name','=',res_model)]")
    note = fields.Text('Note')

    @api.onchange('res_model')
    def _onchange_res_model(self):
        if self.res_model:
            defs = self.env['wf.definition'].search([
                ('state', '=', 'active'),
                ('model_name', '=', self.res_model),
            ])
            if len(defs) == 1:
                self.definition_id = defs[0]

    def action_start(self):
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError(_('Record not found.'))
        instance = self.definition_id.trigger_for_record(record)
        if not instance:
            raise UserError(_(
                'Could not start the workflow. The record may not match the '
                'trigger conditions, or an active instance already exists.'))
        if self.note:
            instance._log_event('info', f'Manually started: {self.note}')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wf.instance',
            'res_id': instance.id,
            'view_mode': 'form',
        }
