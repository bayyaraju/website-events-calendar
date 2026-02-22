# -*- coding: utf-8 -*-
import json
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class WorkflowTransition(models.Model):
    """An edge between two stages. Carries condition, permissions and actions."""
    _name = 'wf.transition'
    _description = 'Workflow Transition'
    _order = 'sequence, id'

    name     = fields.Char('Label',    required=True)
    sequence = fields.Integer('Seq',   default=10)
    active   = fields.Boolean(default=True)

    definition_id = fields.Many2one(
        'wf.definition', required=True, ondelete='cascade', index=True)
    from_stage_id = fields.Many2one(
        'wf.stage', 'From Stage', required=True, ondelete='cascade',
        domain="[('definition_id','=',definition_id)]")
    to_stage_id   = fields.Many2one(
        'wf.stage', 'To Stage',   required=True, ondelete='cascade',
        domain="[('definition_id','=',definition_id)]")

    # ── Trigger ──────────────────────────────────────────────────────────────
    trigger_type = fields.Selection([
        ('manual',           'Manual'),
        ('auto',             'Automatic'),
        ('button',           'Button'),
        ('approval_granted', 'Approval Granted'),
        ('approval_rejected','Approval Rejected'),
        ('sla_breach',       'SLA Breach'),
        ('api',              'External API'),
    ], default='manual', required=True)

    button_label = fields.Char('Button Label')
    button_style = fields.Selection([
        ('btn-primary',   'Primary'),
        ('btn-success',   'Success'),
        ('btn-warning',   'Warning'),
        ('btn-danger',    'Danger'),
        ('btn-secondary', 'Secondary'),
    ], default='btn-primary')
    button_icon = fields.Char('Button Icon', default='fa-arrow-right')

    # ── Condition ────────────────────────────────────────────────────────────
    condition_type = fields.Selection([
        ('none',        'None'),
        ('domain',      'Domain'),
        ('python',      'Python Expression'),
        ('field_value', 'Field Value'),
        ('group',       'User Group'),
    ], default='none', required=True)

    condition_domain   = fields.Char('Domain',      default='[]')
    condition_python   = fields.Text('Python',      help='Must evaluate to True/False.\nAvailable: record, env, user, instance')
    condition_field_id = fields.Many2one('ir.model.fields', 'Field',
                                         domain="[('model_id','=',definition_id.model_id)]")
    condition_operator = fields.Selection([
        ('=','='), ('!=','≠'), ('>','>'), ('>=','≥'), ('<','<'), ('<=','≤'),
        ('in','in'), ('not in','not in'), ('ilike','contains'),
    ], default='=')
    condition_value    = fields.Char('Value')

    # ── Permissions ──────────────────────────────────────────────────────────
    allowed_user_ids  = fields.Many2many(
        'res.users',  'wf_trans_user_rel',  'trans_id', 'user_id',  'Allowed Users')
    allowed_group_ids = fields.Many2many(
        'res.groups', 'wf_trans_group_rel', 'trans_id', 'group_id', 'Allowed Groups')

    # ── Validation ───────────────────────────────────────────────────────────
    require_comment  = fields.Boolean('Require Comment', default=False)
    confirm_message  = fields.Char('Confirmation Message')

    # ── Actions on traversal ─────────────────────────────────────────────────
    action_ids = fields.One2many('wf.action', 'transition_id', 'Actions')

    # ── Canvas path ──────────────────────────────────────────────────────────
    path_data = fields.Text('SVG Path Data')

    _no_self_loop = models.Constraint(
        'CHECK(from_stage_id != to_stage_id)',
        'A transition cannot loop to the same stage.'
    )

    # ── Condition evaluation ─────────────────────────────────────────────────
    def _evaluate_condition(self, instance):
        self.ensure_one()
        record = self.env[instance.res_model].browse(instance.res_id)
        ctype  = self.condition_type

        if ctype == 'none':
            return True

        if ctype == 'domain':
            try:
                domain = json.loads(self.condition_domain or '[]')
                return bool(self.env[instance.res_model].search(
                    [('id', '=', record.id)] + domain))
            except Exception as e:
                _logger.warning('WF domain condition error: %s', e)
                return False

        if ctype == 'python':
            try:
                ctx = self._eval_ctx(record, instance)
                return bool(safe_eval(self.condition_python or 'True', ctx))
            except Exception as e:
                _logger.warning('WF python condition error: %s', e)
                return False

        if ctype == 'field_value':
            if not self.condition_field_id:
                return True
            val = getattr(record, self.condition_field_id.name, None)
            op  = self.condition_operator or '='
            cval = self.condition_value
            try:
                if op == '=':   return str(val) == cval
                if op == '!=':  return str(val) != cval
                if op == '>':   return float(val or 0) >  float(cval or 0)
                if op == '>=':  return float(val or 0) >= float(cval or 0)
                if op == '<':   return float(val or 0) <  float(cval or 0)
                if op == '<=':  return float(val or 0) <= float(cval or 0)
                if op == 'in':
                    return str(val) in [v.strip() for v in (cval or '').split(',')]
                if op == 'not in':
                    return str(val) not in [v.strip() for v in (cval or '').split(',')]
                if op == 'ilike':
                    return (cval or '').lower() in str(val or '').lower()
            except Exception:
                return False

        if ctype == 'group':
            return any(self.env.user in g.users for g in self.allowed_group_ids)

        return True

    def _check_user_permission(self):
        self.ensure_one()
        if not self.allowed_user_ids and not self.allowed_group_ids:
            return True
        if self.allowed_user_ids and self.env.user in self.allowed_user_ids:
            return True
        return any(self.env.user in g.users for g in self.allowed_group_ids)

    @staticmethod
    def _eval_ctx(record, instance):
        return {
            'record': record, 'env': record.env,
            'user': record.env.user, 'instance': instance,
            'datetime': __import__('datetime'),
            'True': True, 'False': False, 'None': None,
        }

    # ── Execution ────────────────────────────────────────────────────────────
    def execute(self, instance, comment=None):
        """Execute this transition: exit old stage → run actions → enter new stage."""
        self.ensure_one()
        if not self._check_user_permission():
            raise UserError(_('You do not have permission to take: %s') % self.name)
        if self.require_comment and not comment:
            raise UserError(_('A comment is required for transition: %s') % self.name)

        # Exit old stage
        for act in self.from_stage_id.exit_action_ids.filtered('active').sorted('sequence'):
            act.execute(instance)

        # Log
        instance._log_transition(self, comment=comment)

        # Transition actions
        for act in self.action_ids.filtered('active').sorted('sequence'):
            act.execute(instance)

        # Move
        instance.write({'current_stage_id': self.to_stage_id.id, 'state': 'running'})

        # Enter new stage
        instance._on_enter_stage()

        # Check completion
        if self.to_stage_id.stage_type == 'end':
            instance._complete()

        return True
