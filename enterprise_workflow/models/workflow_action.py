# -*- coding: utf-8 -*-
import json
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class WorkflowAction(models.Model):
    """
    An action executed during workflow: on stage entry/exit or on transition.
    Supports 14 action types covering field updates, email, webhooks,
    activities, server actions, Python code, chatter and more.
    """
    _name = 'wf.action'
    _description = 'Workflow Action'
    _order = 'sequence, id'

    name     = fields.Char('Name',     required=True)
    sequence = fields.Integer('Seq',   default=10)
    active   = fields.Boolean(default=True)
    description = fields.Text('Description')

    # Parent (only one should be set)
    definition_id  = fields.Many2one('wf.definition',  ondelete='cascade', index=True)
    entry_stage_id = fields.Many2one('wf.stage',        ondelete='cascade', index=True)
    exit_stage_id  = fields.Many2one('wf.stage',        ondelete='cascade', index=True)
    transition_id  = fields.Many2one('wf.transition',   ondelete='cascade', index=True)

    # ── Action type ───────────────────────────────────────────────────────────
    action_type = fields.Selection([
        ('update_field',       'Update Field'),
        ('send_email',         'Send Email'),
        ('send_sms',           'Send SMS'),
        ('create_activity',    'Create Activity'),
        ('server_action',      'Server Action'),
        ('python_code',        'Python Code'),
        ('webhook',            'Webhook / REST API'),
        ('create_record',      'Create Record'),
        ('assign_user',        'Assign User'),
        ('send_notification',  'In-App Notification'),
        ('start_sub_workflow', 'Start Sub-Workflow'),
        ('write_chatter',      'Post to Chatter'),
    ], required=True, default='update_field')

    # ── Update field ─────────────────────────────────────────────────────────
    field_id = fields.Many2one('ir.model.fields', 'Field',
                               domain="[('model_id','=',definition_id.model_id),('readonly','=',False)]")
    field_value       = fields.Char('New Value / Expression')
    field_value_type  = fields.Selection([
        ('literal',         'Literal'),
        ('python',          'Python Expression'),
        ('field_reference', 'Copy from Field'),
    ], default='literal')

    # ── Email ─────────────────────────────────────────────────────────────────
    email_template_id = fields.Many2one('mail.template', 'Email Template',
                                         domain="[('model_id','=',definition_id.model_id)]")
    email_to = fields.Char('Email To (expression)')

    # ── Activity ──────────────────────────────────────────────────────────────
    activity_type_id      = fields.Many2one('mail.activity.type', 'Activity Type')
    activity_summary      = fields.Char('Summary')
    activity_note         = fields.Text('Note')
    activity_deadline_days = fields.Integer('Deadline (days)', default=1)
    activity_user_id      = fields.Many2one('res.users', 'Assign To (User)')
    activity_user_field_id = fields.Many2one(
        'ir.model.fields', 'Assign To (Field)',
        domain="[('model_id','=',definition_id.model_id),"
               "('ttype','=','many2one'),('relation','=','res.users')]")

    # ── Server action ─────────────────────────────────────────────────────────
    server_action_id = fields.Many2one('ir.actions.server', 'Server Action',
                                        domain="[('model_id','=',definition_id.model_id)]")

    # ── Python code ───────────────────────────────────────────────────────────
    python_code = fields.Text('Python Code',
                               help='Available: record, env, user, instance, datetime')

    # ── Webhook ───────────────────────────────────────────────────────────────
    webhook_url     = fields.Char('URL')
    webhook_method  = fields.Selection([
        ('GET','GET'), ('POST','POST'), ('PUT','PUT'),
        ('PATCH','PATCH'), ('DELETE','DELETE'),
    ], default='POST')
    webhook_headers = fields.Text('Headers (JSON)',
                                   default='{"Content-Type": "application/json"}')
    webhook_body    = fields.Text('Body (Python dict expression)')
    webhook_timeout = fields.Integer('Timeout (s)', default=30)
    webhook_on_error = fields.Selection([
        ('ignore','Ignore'), ('log','Log'), ('raise','Raise'),
    ], default='log')

    # ── Create record ─────────────────────────────────────────────────────────
    create_model_id = fields.Many2one('ir.model', 'Model to Create')
    create_values   = fields.Text('Values (Python dict expression)')

    # ── Notification ──────────────────────────────────────────────────────────
    notification_message  = fields.Text('Message')
    notification_user_ids = fields.Many2many(
        'res.users', 'wf_action_notif_rel', 'action_id', 'user_id', 'Notify Users')

    # ── Chatter ───────────────────────────────────────────────────────────────
    chatter_message  = fields.Text('Message (expression or text)')
    chatter_subtype  = fields.Char('Subtype', default='mail.mt_note')

    # ── Optional condition ────────────────────────────────────────────────────
    has_condition      = fields.Boolean('Conditional')
    condition_python   = fields.Text('Condition (Python)')

    # ── Dispatch ─────────────────────────────────────────────────────────────
    def execute(self, instance):
        self.ensure_one()
        record = self.env[instance.res_model].browse(instance.res_id)

        if self.has_condition and self.condition_python:
            try:
                if not safe_eval(self.condition_python, self._ctx(record, instance)):
                    return
            except Exception as e:
                _logger.warning('Action condition error [%s]: %s', self.name, e)
                return

        try:
            method = getattr(self, f'_do_{self.action_type}', None)
            if method:
                method(record, instance)
            else:
                _logger.warning('Unknown action type: %s', self.action_type)
        except Exception as e:
            _logger.error('Action [%s] failed: %s', self.name, e, exc_info=True)
            instance._log_error(f'Action "{self.name}" failed: {e}')
            raise

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _ctx(record, instance):
        return {
            'record': record, 'env': record.env,
            'user': record.env.user, 'instance': instance,
            'datetime': __import__('datetime'),
            'True': True, 'False': False, 'None': None,
        }

    def _eval(self, expr, record, instance):
        if not expr:
            return None
        try:
            return safe_eval(str(expr), self._ctx(record, instance))
        except Exception:
            return expr

    # ── Action implementations ────────────────────────────────────────────────
    def _do_update_field(self, record, instance):
        if not self.field_id:
            return
        fname = self.field_id.name
        ftype = self.field_id.ttype
        if self.field_value_type == 'python':
            val = self._eval(self.field_value, record, instance)
        elif self.field_value_type == 'field_reference':
            val = getattr(record, self.field_value, None)
        else:
            val = self.field_value
            if ftype == 'integer':
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    pass
            elif ftype in ('float', 'monetary'):
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    pass
            elif ftype == 'boolean':
                val = str(val).lower() in ('true', '1', 'yes')
        record.write({fname: val})

    def _do_send_email(self, record, instance):
        if self.email_template_id:
            self.email_template_id.send_mail(record.id, force_send=True)
        elif self.email_to:
            email_to = self._eval(self.email_to, record, instance)
            record.message_notify(
                body=_('Workflow notification: %s') % instance.definition_id.name,
                email_to=str(email_to),
                subject=_('[Workflow] %s') % instance.definition_id.name,
            )

    def _do_create_activity(self, record, instance):
        if not self.activity_type_id:
            return
        import datetime as dt
        deadline = dt.date.today() + dt.timedelta(days=self.activity_deadline_days or 1)
        user_id = self.activity_user_id.id if self.activity_user_id else record.env.user.id
        if self.activity_user_field_id:
            fv = getattr(record, self.activity_user_field_id.name, None)
            if fv:
                user_id = fv.id
        record.activity_schedule(
            activity_type_id=self.activity_type_id.id,
            summary=self.activity_summary or '',
            note=self.activity_note or '',
            date_deadline=deadline,
            user_id=user_id,
        )

    def _do_server_action(self, record, instance):
        if self.server_action_id:
            ctx = {'active_id': record.id, 'active_ids': [record.id],
                   'active_model': record._name}
            self.server_action_id.with_context(**ctx).run()

    def _do_python_code(self, record, instance):
        if self.python_code:
            safe_eval(self.python_code, self._ctx(record, instance),
                      mode='exec', nocopy=True)

    def _do_webhook(self, record, instance):
        if not self.webhook_url:
            return
        import requests as req
        url = self._eval(self.webhook_url, record, instance) or self.webhook_url
        try:
            headers = json.loads(self.webhook_headers or '{}')
        except Exception:
            headers = {'Content-Type': 'application/json'}
        body = None
        if self.webhook_body:
            try:
                body = json.dumps(self._eval(self.webhook_body, record, instance))
            except Exception:
                body = self.webhook_body
        try:
            resp = req.request(
                method=self.webhook_method or 'POST',
                url=url, headers=headers, data=body,
                timeout=self.webhook_timeout or 30)
            resp.raise_for_status()
        except Exception as e:
            msg = f'Webhook failed: {e}'
            if self.webhook_on_error == 'raise':
                raise UserError(msg)
            elif self.webhook_on_error == 'log':
                _logger.error(msg)
                instance._log_error(msg)

    def _do_create_record(self, record, instance):
        if not self.create_model_id or not self.create_values:
            return
        vals = self._eval(self.create_values, record, instance)
        if isinstance(vals, dict):
            self.env[self.create_model_id.model].create(vals)

    def _do_assign_user(self, record, instance):
        user = self.activity_user_id
        if not user:
            return
        for fname in ('user_id', 'responsible_id', 'assigned_to'):
            if hasattr(record, fname):
                record.write({fname: user.id})
                return

    def _do_send_notification(self, record, instance):
        if not self.notification_message:
            return
        msg = self._eval(self.notification_message, record, instance)
        users = self.notification_user_ids or record.env.user
        record.message_notify(
            partner_ids=users.mapped('partner_id').ids,
            body=str(msg),
            subject=_('[Workflow] %s') % instance.definition_id.name,
        )

    def _do_start_sub_workflow(self, record, instance):
        sub = instance.current_stage_id.sub_workflow_id
        if sub and sub.state == 'active':
            sub.trigger_for_record(record)

    def _do_write_chatter(self, record, instance):
        if not self.chatter_message:
            return
        msg = self._eval(self.chatter_message, record, instance)
        if hasattr(record, 'message_post'):
            record.message_post(body=str(msg))
