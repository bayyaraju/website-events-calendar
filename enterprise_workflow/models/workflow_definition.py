# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class WorkflowDefinition(models.Model):
    """
    Workflow Definition — the blueprint/template for a workflow process.
    Stores stages, transitions, SLAs, trigger config and designer layout.
    """
    _name = 'wf.definition'
    _description = 'Workflow Definition'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    # ── Identity ────────────────────────────────────────────────────────────
    name = fields.Char('Name', required=True, tracking=True)
    code = fields.Char('Technical Code', required=True, index=True, copy=False,
                       help='Unique identifier — no spaces.')
    description = fields.Text('Description')
    sequence = fields.Integer('Sequence', default=10)
    color = fields.Integer('Color Index', default=0)
    active = fields.Boolean('Active', default=True, tracking=True)

    # ── Target model ────────────────────────────────────────────────────────
    model_id = fields.Many2one('ir.model', 'Target Model',
                               ondelete='set null', tracking=True)
    model_name = fields.Char(related='model_id.model', store=True, readonly=True)

    # ── State & versioning ──────────────────────────────────────────────────
    state = fields.Selection([
        ('draft',      'Draft'),
        ('active',     'Active'),
        ('deprecated', 'Deprecated'),
    ], default='draft', required=True, tracking=True)

    version = fields.Integer('Version', default=1, readonly=True, copy=False)
    version_notes = fields.Text('Version Notes')
    parent_id = fields.Many2one('wf.definition', 'Previous Version',
                                readonly=True, copy=False)

    # ── Trigger ─────────────────────────────────────────────────────────────
    trigger_type = fields.Selection([
        ('manual',          'Manual'),
        ('on_create',       'On Record Create'),
        ('on_write',        'On Record Update'),
        ('on_create_write', 'On Create or Update'),
        ('scheduled',       'Scheduled (Cron)'),
        ('webhook',         'Webhook / API'),
    ], default='manual', required=True, tracking=True)

    trigger_domain = fields.Char('Trigger Domain', default='[]',
                                 help='Domain filter — only matching records trigger the workflow.')
    trigger_field_ids = fields.Many2many(
        'ir.model.fields', 'wf_def_trigger_field_rel', 'def_id', 'field_id',
        string='Trigger Fields',
        domain="[('model_id','=',model_id)]",
        help='For on_write: only fire when these fields change.')
    cron_expression = fields.Char('Cron Expression', help='e.g. 0 9 * * 1-5')

    # ── Relations ───────────────────────────────────────────────────────────
    stage_ids      = fields.One2many('wf.stage',      'definition_id', 'Stages')
    transition_ids = fields.One2many('wf.transition', 'definition_id', 'Transitions')
    sla_ids        = fields.One2many('wf.sla',        'definition_id', 'SLA Rules')
    instance_ids   = fields.One2many('wf.instance',   'definition_id', 'Instances')

    # ── Settings ────────────────────────────────────────────────────────────
    allow_parallel        = fields.Boolean('Allow Parallel Instances', default=False)
    auto_close            = fields.Boolean('Auto-Close on Completion',  default=True)
    notify_on_complete    = fields.Boolean('Notify on Completion',       default=False)
    notify_template_id    = fields.Many2one(
        'mail.template', 'Completion Template',
        domain="[('model_id','=',model_id)]")

    # ── Designer canvas layout ───────────────────────────────────────────────
    canvas_data = fields.Text('Canvas Data', help='JSON — stores node positions.')

    # ── Computed ────────────────────────────────────────────────────────────
    stage_count           = fields.Integer(compute='_compute_counts')
    instance_count        = fields.Integer(compute='_compute_counts')
    active_instance_count = fields.Integer(compute='_compute_counts')

    _code_uniq = models.Constraint(
        'UNIQUE(code)', 'Workflow code must be unique.'
    )

    @api.depends('stage_ids', 'instance_ids')
    def _compute_counts(self):
        for r in self:
            r.stage_count           = len(r.stage_ids)
            r.instance_count        = len(r.instance_ids)
            r.active_instance_count = len(r.instance_ids.filtered(
                lambda i: i.state in ('running', 'waiting', 'pending_approval')))

    @api.constrains('code')
    def _check_code(self):
        for r in self:
            if ' ' in (r.code or ''):
                raise ValidationError(_('Workflow code must not contain spaces.'))

    # ── State transitions ────────────────────────────────────────────────────
    def action_activate(self):
        for r in self:
            if not r.stage_ids:
                raise UserError(_('Add at least one stage before activating.'))
            if not r.stage_ids.filtered(lambda s: s.stage_type == 'start'):
                raise UserError(_('Workflow needs a Start stage.'))
            if not r.stage_ids.filtered(lambda s: s.stage_type == 'end'):
                raise UserError(_('Workflow needs an End stage.'))
            r.state = 'active'
            r.message_post(body=_('Workflow activated (v%s).') % r.version)

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def action_deprecate(self):
        for r in self:
            r.state = 'deprecated'
            r.message_post(body=_('Workflow deprecated.'))

    def action_new_version(self):
        self.ensure_one()
        new = self.copy({
            'code':    f'{self.code}_v{self.version + 1}',
            'version': self.version + 1,
            'state':   'draft',
            'parent_id': self.id,
        })
        self.action_deprecate()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wf.definition',
            'res_id': new.id,
            'view_mode': 'form',
        }

    # ── Business logic ───────────────────────────────────────────────────────
    def _get_start_stage(self):
        self.ensure_one()
        start = self.stage_ids.filtered(lambda s: s.stage_type == 'start')
        if not start:
            raise UserError(_('No start stage in workflow: %s') % self.name)
        return start[0]

    def trigger_for_record(self, record):
        """
        Start a new workflow instance on *record*.
        Returns the created wf.instance or False.
        """
        self.ensure_one()
        if self.state != 'active':
            return False

        if not self.allow_parallel:
            existing = self.env['wf.instance'].search([
                ('definition_id', '=', self.id),
                ('res_model', '=', record._name),
                ('res_id', '=', record.id),
                ('state', 'in', ('running', 'waiting', 'pending_approval')),
            ], limit=1)
            if existing:
                return False

        # Domain filter
        if self.trigger_domain and self.trigger_domain != '[]':
            try:
                domain = json.loads(self.trigger_domain)
                if not self.env[record._name].search([('id', '=', record.id)] + domain):
                    return False
            except Exception:
                pass

        instance = self.env['wf.instance'].create({
            'definition_id':   self.id,
            'res_model':       record._name,
            'res_id':          record.id,
            'res_name':        record.display_name,
            'current_stage_id': self._get_start_stage().id,
            'state':           'running',
        })
        instance._on_enter_stage()
        return instance

    def action_view_instances(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Instances — %s') % self.name,
            'res_model': 'wf.instance',
            'view_mode': 'list,form',
            'domain': [('definition_id', '=', self.id)],
        }
