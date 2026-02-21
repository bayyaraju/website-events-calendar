# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ClaudeConfig(models.Model):
    _name = 'claude.config'
    _description = 'Claude AI Configuration'
    _inherit = ['mail.thread']

    name = fields.Char(default='Default Configuration')
    active = fields.Boolean(default=False)

    # ── API ────────────────────────────────────────────────────────────────
    api_key = fields.Char(string='Anthropic API Key', copy=False)
    model_name = fields.Selection([
        ('claude-opus-4-5',     'Claude Opus 4.5 (Most Capable)'),
        ('claude-sonnet-4-5',   'Claude Sonnet 4.5 (Recommended)'),
        ('claude-haiku-4-5',    'Claude Haiku 4.5 (Fast)'),
    ], string='Model', default='claude-sonnet-4-5', required=True)
    max_tokens       = fields.Integer(default=8096)
    temperature      = fields.Float(default=0.3)
    request_timeout  = fields.Integer(string='Timeout (sec)', default=60)

    # ── Behaviour ──────────────────────────────────────────────────────────
    require_confirmation = fields.Boolean(
        string='Confirm Write Operations', default=False,
        help='Ask user to confirm before Claude creates/updates/deletes records',
    )
    log_all_actions = fields.Boolean(default=True)
    system_prompt   = fields.Text(
        default=(
            'You are Claude, an AI assistant deeply integrated with Odoo 19. '
            'You have full access to all Odoo models and data. '
            'When asked about Odoo data, query it accurately and return clear results. '
            'For write operations, generate a JSON operation block so the system can execute it. '
            'Format Odoo operations as:\n```odoo_op\n{"model":"...","method":"...","args":[],"kwargs":{}}\n```'
        ),
    )

    # ── Status ─────────────────────────────────────────────────────────────
    connection_status  = fields.Selection(
        [('untested','Not Tested'),('ok','Connected'),('error','Error')],
        default='untested',
    )
    connection_message = fields.Text(readonly=True)
    last_tested        = fields.Datetime(readonly=True)

    # ──────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ──────────────────────────────────────────────────────────────────────
    def write(self, vals):
        """Never overwrite api_key with an empty value.
        When a record is set active=True, deactivate all others (mutual exclusion)."""
        if 'api_key' in vals and not (vals.get('api_key') or '').strip():
            vals.pop('api_key')
        result = super().write(vals)
        if vals.get('active') and not self.env.context.get('skip_active_check'):
            others = self.sudo().search([('id', 'not in', self.ids), ('active', '=', True)])
            if others:
                others.with_context(skip_active_check=True).write({'active': False})
        return result

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────
    @api.model
    def get_active_config(self):
        """Return the config with active=True; fall back to any record."""
        config = self.sudo().search([('active', '=', True)], limit=1)
        if not config:
            config = self.sudo().search([], limit=1)
        if not config:
            raise UserError(
                'No Claude AI configuration found. '
                'Go to Claude AI → Configuration and save your settings.'
            )
        return config

    def _get_api_key(self):
        """Raw SQL read of this config's api_key — bypasses all ORM caching."""
        self.ensure_one()
        self.env.cr.execute(
            'SELECT api_key FROM claude_config WHERE id = %s', (self.id,)
        )
        row = self.env.cr.fetchone()
        return (row[0] or '').strip() if row else ''

    def action_set_active(self):
        """Mark this config as the active one; deactivate all others."""
        self.ensure_one()
        others = self.sudo().search([('id', '!=', self.id), ('active', '=', True)])
        others.with_context(skip_active_check=True).write({'active': False})
        self.with_context(skip_active_check=True).write({'active': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Configuration Activated',
                'message': f'"{self.name}" is now the active configuration.',
                'type': 'success',
                'sticky': False,
            },
        }

    # ──────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────
    def action_test_connection(self):
        self.ensure_one()
        api_key = self._get_api_key()
        if not api_key:
            raise UserError('Please enter and save your Anthropic API key first.')
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model=self.model_name,
                max_tokens=16,
                messages=[{'role': 'user', 'content': 'Reply with: OK'}],
            )
            reply = msg.content[0].text.strip() if msg.content else '(no response)'
            self.write({
                'connection_status': 'ok',
                'connection_message': f'Connected! Model responded: {reply}',
                'last_tested': fields.Datetime.now(),
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Successful',
                    'message': 'Claude AI is connected and working.',
                    'type': 'success',
                },
            }
        except ImportError:
            err = 'anthropic package not installed. Run: pip install anthropic'
            self.write({'connection_status': 'error', 'connection_message': err,
                        'last_tested': fields.Datetime.now()})
            raise UserError(err)
        except Exception as e:
            self.write({'connection_status': 'error', 'connection_message': str(e),
                        'last_tested': fields.Datetime.now()})
            raise UserError(f'Connection failed: {e}')
