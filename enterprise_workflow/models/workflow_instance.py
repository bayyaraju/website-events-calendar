# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WorkflowInstance(models.Model):
    """
    A running (or completed) workflow execution on a specific record.
    Tracks current stage, approvals, SLA deadline and full history.
    """
    _name = 'wf.instance'
    _description = 'Workflow Instance'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char('Reference', required=True, copy=False,
                       default=lambda self: _('New'), readonly=True)

    definition_id = fields.Many2one(
        'wf.definition', 'Workflow',
        ondelete='restrict', index=True, readonly=True)

    # ── Target record ─────────────────────────────────────────────────────────
    res_model = fields.Char('Model',       required=True, readonly=True, index=True)
    res_id    = fields.Integer('Record ID', required=True, readonly=True, index=True)
    res_name  = fields.Char('Record Name', readonly=True)

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('running',          'Running'),
        ('waiting',          'Waiting'),
        ('pending_approval', 'Pending Approval'),
        ('completed',        'Completed'),
        ('cancelled',        'Cancelled'),
        ('error',            'Error'),
        ('sla_breached',     'SLA Breached'),
    ], default='running', required=True, tracking=True, index=True)

    current_stage_id   = fields.Many2one('wf.stage', 'Current Stage',
                                          ondelete='restrict', tracking=True)
    current_stage_name = fields.Char(related='current_stage_id.name', store=True)

    # ── Timing ────────────────────────────────────────────────────────────────
    started_at       = fields.Datetime('Started',       default=fields.Datetime.now, readonly=True)
    completed_at     = fields.Datetime('Completed',     readonly=True)
    stage_entered_at = fields.Datetime('Stage Entered', default=fields.Datetime.now)
    sla_deadline     = fields.Datetime('SLA Deadline')
    duration_hours   = fields.Float(compute='_compute_duration', store=True, string='Duration (h)')

    # ── Assignments ───────────────────────────────────────────────────────────
    owner_id         = fields.Many2one('res.users', 'Owner',
                                        default=lambda self: self.env.user, index=True)
    assigned_user_id = fields.Many2one('res.users', 'Assigned To', tracking=True)

    # ── Relations ─────────────────────────────────────────────────────────────
    approval_ids = fields.One2many('wf.approval', 'instance_id', 'Approvals')
    log_ids      = fields.One2many('wf.instance.log', 'instance_id', 'Log')

    pending_approval_count = fields.Integer(compute='_compute_pending_approvals')

    # ── Runtime variables (key-value store) ──────────────────────────────────
    variables_json = fields.Text('Variables (JSON)', default='{}')

    # ── Computed ──────────────────────────────────────────────────────────────
    @api.depends('started_at', 'completed_at', 'state')
    def _compute_duration(self):
        for r in self:
            if r.started_at:
                end = r.completed_at or fields.Datetime.now()
                r.duration_hours = (end - r.started_at).total_seconds() / 3600
            else:
                r.duration_hours = 0.0

    @api.depends('approval_ids.state')
    def _compute_pending_approvals(self):
        for r in self:
            r.pending_approval_count = len(
                r.approval_ids.filtered(lambda a: a.state == 'pending'))

    # ── ORM ───────────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get('name', _('New')) == _('New'):
                v['name'] = self.env['ir.sequence'].next_by_code('wf.instance') or _('New')
        return super().create(vals_list)

    # ── Variables ─────────────────────────────────────────────────────────────
    def get_var(self, key, default=None):
        self.ensure_one()
        try:
            return json.loads(self.variables_json or '{}').get(key, default)
        except Exception:
            return default

    def set_var(self, key, value):
        self.ensure_one()
        try:
            d = json.loads(self.variables_json or '{}')
        except Exception:
            d = {}
        d[key] = value
        self.variables_json = json.dumps(d)

    # ── Stage lifecycle ───────────────────────────────────────────────────────
    def _on_enter_stage(self):
        """Called whenever the instance moves into a new stage."""
        self.ensure_one()
        self.write({'stage_entered_at': fields.Datetime.now()})

        stage = self.current_stage_id

        # Set SLA deadline
        if stage.sla_hours:
            self.sla_deadline = datetime.now() + timedelta(hours=stage.sla_hours)
        else:
            self.sla_deadline = False

        # Handle approval stage
        if stage.stage_type == 'approval':
            self._create_approval_requests()
            self.state = 'pending_approval'

        # Entry actions
        for act in stage.entry_action_ids.filtered('active').sorted('sequence'):
            try:
                act.execute(self)
            except Exception as e:
                _logger.error('Entry action error: %s', e)
                self._log_error(str(e))

        # Auto-advance
        if stage.auto_advance and stage.stage_type != 'approval':
            if stage.auto_advance_delay:
                self.set_var('_auto_advance_at',
                             (datetime.now() + timedelta(minutes=stage.auto_advance_delay)).isoformat())
            else:
                self._try_auto_advance()

        self._log_stage_entry()

    def _try_auto_advance(self):
        self.ensure_one()
        for t in self.current_stage_id.outgoing_transition_ids.filtered(
                lambda x: x.trigger_type == 'auto' and x.active).sorted('sequence'):
            if t._evaluate_condition(self):
                t.execute(self)
                return

    # ── Approvals ─────────────────────────────────────────────────────────────
    def _create_approval_requests(self):
        self.ensure_one()
        stage = self.current_stage_id
        approvers = self._resolve_approvers(stage)
        record = self.env[self.res_model].browse(self.res_id)

        for user in approvers:
            self.env['wf.approval'].create({
                'instance_id': self.id,
                'stage_id':    stage.id,
                'approver_id': user.id,
                'state':       'pending',
            })
            if hasattr(record, 'message_notify'):
                record.message_notify(
                    partner_ids=user.partner_id.ids,
                    body=_('Your approval is needed for: <b>%s</b> — Stage: %s')
                         % (self.definition_id.name, stage.name),
                    subject=_('[Approval Needed] %s') % self.definition_id.name,
                )

    def _resolve_approvers(self, stage):
        approvers = stage.approver_ids
        for g in stage.approver_group_ids:
            approvers |= g.users
        if stage.approver_field_id:
            record = self.env[self.res_model].browse(self.res_id)
            fv = getattr(record, stage.approver_field_id.name, None)
            if fv:
                if hasattr(fv, '__iter__'):
                    for u in fv:
                        if isinstance(u, type(self.env['res.users'])):
                            approvers |= u
                elif isinstance(fv, type(self.env['res.users'])):
                    approvers |= fv
        return approvers or (self.owner_id or self.env.user)

    def _check_approval_completion(self):
        self.ensure_one()
        stage = self.current_stage_id
        approvals = self.approval_ids.filtered(lambda a: a.stage_id == stage)
        total    = len(approvals)
        approved = len(approvals.filtered(lambda a: a.state == 'approved'))
        rejected = len(approvals.filtered(lambda a: a.state == 'rejected'))

        atype = stage.approval_type
        done_approved = False
        done_rejected = False

        if atype == 'single':
            if approved >= 1:  done_approved = True
            if rejected >= 1:  done_rejected = True
        elif atype == 'any':
            if approved >= 1:  done_approved = True
            if rejected >= 1:  done_rejected = True
        elif atype == 'all':
            if rejected > 0:   done_rejected = True
            elif approved == total: done_approved = True
        elif atype == 'majority':
            if approved > total / 2:   done_approved = True
            elif rejected > total / 2: done_rejected = True
        elif atype == 'sequential':
            if not approvals.filtered(lambda a: a.state == 'pending'):
                if rejected:   done_rejected = True
                else:          done_approved = True

        if done_rejected:
            self._process_approval_result('rejected')
        elif done_approved:
            self._process_approval_result('approved')

    def _process_approval_result(self, result):
        trigger = 'approval_granted' if result == 'approved' else 'approval_rejected'
        self.state = 'running'
        for t in self.current_stage_id.outgoing_transition_ids.filtered(
                lambda x: x.trigger_type == trigger and x.active).sorted('sequence'):
            if t._evaluate_condition(self):
                t.execute(self)
                return

    # ── Completion & control ──────────────────────────────────────────────────
    def _complete(self):
        self.ensure_one()
        self.write({'state': 'completed', 'completed_at': fields.Datetime.now()})
        self._log_event('completed', 'Workflow completed successfully.')
        if self.definition_id.notify_on_complete and self.definition_id.notify_template_id:
            record = self.env[self.res_model].browse(self.res_id)
            self.definition_id.notify_template_id.send_mail(record.id, force_send=True)
        record = self.env[self.res_model].browse(self.res_id)
        if hasattr(record, 'message_post'):
            record.message_post(
                body=_('✅ Workflow <b>%s</b> completed in %.1f h.')
                     % (self.definition_id.name, self.duration_hours))

    def action_cancel(self):
        for r in self:
            if r.state in ('completed', 'cancelled'):
                raise UserError(_('Cannot cancel a %s instance.') % r.state)
            r.write({'state': 'cancelled', 'completed_at': fields.Datetime.now()})
            r.approval_ids.filtered(lambda a: a.state == 'pending').write({'state': 'cancelled'})
            r._log_event('cancelled', f'Cancelled by {self.env.user.name}.')

    def action_restart(self):
        self.ensure_one()
        if self.state not in ('error', 'cancelled'):
            raise UserError(_('Can only restart error/cancelled instances.'))
        start = self.definition_id._get_start_stage()
        self.write({
            'state': 'running',
            'current_stage_id': start.id,
            'completed_at': False,
            'sla_deadline': False,
            'stage_entered_at': fields.Datetime.now(),
        })
        self._on_enter_stage()

    def take_transition(self, transition_id, comment=None):
        self.ensure_one()
        if self.state not in ('running', 'waiting'):
            raise UserError(_('Instance is not in a state that allows transitions (%s).') % self.state)
        t = self.env['wf.transition'].browse(transition_id)
        if t.from_stage_id != self.current_stage_id:
            raise UserError(_('Transition does not originate from the current stage.'))
        t.execute(self, comment=comment)

    # ── SLA cron ──────────────────────────────────────────────────────────────
    @api.model
    def cron_check_sla(self):
        now = fields.Datetime.now()
        for inst in self.search([
            ('state', 'in', ('running', 'waiting', 'pending_approval')),
            ('sla_deadline', '<', now),
        ]):
            stage = inst.current_stage_id
            inst._log_event('sla_breach', f'SLA breached at stage: {stage.name}')
            if stage.sla_action == 'notify':
                inst._sla_notify()
            elif stage.sla_action == 'escalate':
                inst._escalate()
            elif stage.sla_action == 'auto_advance':
                inst.state = 'running'
                inst._try_auto_advance()
            elif stage.sla_action == 'abort':
                inst.action_cancel()
            if inst.state not in ('cancelled', 'completed'):
                inst.state = 'sla_breached'

    @api.model
    def cron_auto_advance(self):
        """Process delayed auto-advance instances."""
        now = datetime.now()
        for inst in self.search([
            ('state', '=', 'running'),
            ('variables_json', 'like', '_auto_advance_at'),
        ]):
            try:
                at_str = inst.get_var('_auto_advance_at')
                if at_str and datetime.fromisoformat(at_str) <= now:
                    d = json.loads(inst.variables_json or '{}')
                    del d['_auto_advance_at']
                    inst.variables_json = json.dumps(d)
                    inst._try_auto_advance()
            except Exception as e:
                _logger.error('Auto-advance error for %s: %s', inst.name, e)

    def _sla_notify(self):
        record = self.env[self.res_model].browse(self.res_id)
        if hasattr(record, 'message_post'):
            record.message_post(
                body=_('⚠️ SLA breached for <b>%s</b> at stage <b>%s</b>.')
                     % (self.definition_id.name, self.current_stage_id.name),
                partner_ids=(self.owner_id.partner_id.ids if self.owner_id else []))

    def _escalate(self):
        if self.owner_id and self.owner_id.parent_id:
            mgr = self.env['res.users'].search(
                [('partner_id', '=', self.owner_id.parent_id.id)], limit=1)
            if mgr:
                self.assigned_user_id = mgr
        self._sla_notify()

    # ── Logging ───────────────────────────────────────────────────────────────
    def _log_transition(self, transition, comment=None):
        self.env['wf.instance.log'].create({
            'instance_id':   self.id,
            'log_type':      'transition',
            'message':       f'{transition.from_stage_id.name} → {transition.to_stage_id.name} via "{transition.name}"',
            'user_id':       self.env.user.id,
            'comment':       comment,
            'transition_id': transition.id,
            'from_stage_id': transition.from_stage_id.id,
            'to_stage_id':   transition.to_stage_id.id,
        })

    def _log_stage_entry(self):
        self.env['wf.instance.log'].create({
            'instance_id': self.id,
            'log_type':    'stage_entry',
            'message':     f'Entered stage: {self.current_stage_id.name}',
            'user_id':     self.env.user.id,
            'stage_id':    self.current_stage_id.id,
        })

    def _log_event(self, log_type, message):
        self.env['wf.instance.log'].create({
            'instance_id': self.id,
            'log_type':    log_type,
            'message':     message,
            'user_id':     self.env.user.id,
        })

    def _log_error(self, msg):
        self._log_event('error', msg)
        if self.state == 'running':
            self.state = 'error'

    # ── Navigation ────────────────────────────────────────────────────────────
    def action_open_record(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id':    self.res_id,
            'view_mode': 'form',
        }
