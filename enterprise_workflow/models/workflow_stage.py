# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class WorkflowStage(models.Model):
    """A node / state within a workflow definition."""
    _name = 'wf.stage'
    _description = 'Workflow Stage'
    _order = 'sequence, id'

    name = fields.Char('Stage Name', required=True)
    code = fields.Char('Code',        required=True)
    description = fields.Text('Description')
    sequence = fields.Integer('Sequence', default=10)
    color    = fields.Integer('Color',    default=0)

    definition_id = fields.Many2one(
        'wf.definition', 'Workflow', required=True,
        ondelete='cascade', index=True)

    stage_type = fields.Selection([
        ('start',          'Start'),
        ('normal',         'Normal'),
        ('approval',       'Approval'),
        ('condition',      'Decision / Condition'),
        ('parallel_split', 'Parallel Split'),
        ('parallel_join',  'Parallel Join'),
        ('subprocess',     'Sub-Process'),
        ('end',            'End'),
        ('error',          'Error Handler'),
    ], default='normal', required=True)

    # ── Behaviour ────────────────────────────────────────────────────────────
    is_blocking       = fields.Boolean('Blocking Stage', default=False)
    requires_comment  = fields.Boolean('Require Comment on Exit', default=False)
    auto_advance      = fields.Boolean('Auto-Advance', default=False)
    auto_advance_delay = fields.Integer('Auto-Advance Delay (min)', default=0)

    # ── Approval config ──────────────────────────────────────────────────────
    approval_type = fields.Selection([
        ('single',     'Single Approver'),
        ('any',        'Any One of Group'),
        ('all',        'All Must Approve'),
        ('majority',   'Majority'),
        ('sequential', 'Sequential'),
    ], default='single')

    approver_ids = fields.Many2many(
        'res.users', 'wf_stage_approver_user_rel', 'stage_id', 'user_id',
        string='Approvers')
    approver_group_ids = fields.Many2many(
        'res.groups', 'wf_stage_approver_group_rel', 'stage_id', 'group_id',
        string='Approver Groups')
    approver_field_id = fields.Many2one(
        'ir.model.fields', 'Dynamic Approver Field',
        domain="[('model_id','=',definition_id.model_id),"
               "('ttype','in',('many2one','many2many'))]")

    # ── SLA ──────────────────────────────────────────────────────────────────
    sla_hours  = fields.Float('SLA (hours)', default=0.0,
                              help='0 = no SLA for this stage.')
    sla_action = fields.Selection([
        ('notify',       'Notify Owner'),
        ('escalate',     'Escalate to Manager'),
        ('auto_advance', 'Auto-Advance'),
        ('abort',        'Abort Workflow'),
    ], default='notify')

    # ── Actions ──────────────────────────────────────────────────────────────
    entry_action_ids = fields.One2many(
        'wf.action', 'entry_stage_id', 'On Enter Actions')
    exit_action_ids  = fields.One2many(
        'wf.action', 'exit_stage_id',  'On Exit Actions')

    # ── Sub-workflow ─────────────────────────────────────────────────────────
    sub_workflow_id = fields.Many2one(
        'wf.definition', 'Sub-Workflow',
        domain="[('state','=','active')]")

    # ── Canvas position ──────────────────────────────────────────────────────
    pos_x = fields.Integer('Canvas X', default=100)
    pos_y = fields.Integer('Canvas Y', default=100)

    # ── Transitions ──────────────────────────────────────────────────────────
    outgoing_transition_ids = fields.One2many(
        'wf.transition', 'from_stage_id', 'Outgoing Transitions')
    incoming_transition_ids = fields.One2many(
        'wf.transition', 'to_stage_id',   'Incoming Transitions')

    _code_def_uniq = models.Constraint(
        'UNIQUE(code, definition_id)',
        'Stage code must be unique within a workflow.'
    )

    @api.constrains('stage_type', 'definition_id')
    def _check_unique_start(self):
        for r in self:
            if r.stage_type == 'start':
                others = self.search([
                    ('definition_id', '=', r.definition_id.id),
                    ('stage_type',    '=', 'start'),
                    ('id',            '!=', r.id),
                ])
                if others:
                    raise ValidationError(_('A workflow can only have one Start stage.'))

    def get_available_transitions(self, instance):
        """Return transitions from this stage that pass their condition check."""
        self.ensure_one()
        return [t for t in self.outgoing_transition_ids.sorted('sequence')
                if t._evaluate_condition(instance)]
