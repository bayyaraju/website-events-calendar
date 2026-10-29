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
        ('claude-opus-5-5',           'Claude Opus 5.5 (Most Capable)'),
        ('claude-sonnet-5-5',         'Claude Sonnet 5.5 (Recommended)'),
        ('claude-haiku-4-5-20251001', 'Claude Haiku 4.5 (Fast, Low Cost)'),
        ('claude-fable-5-1',          'Claude Fable 5.1'),
        # legacy values kept so existing configurations keep working
        ('claude-opus-4-5',           'Claude Opus 4.5 (legacy)'),
        ('claude-sonnet-4-5',         'Claude Sonnet 4.5 (legacy)'),
        ('claude-haiku-4-5',          'Claude Haiku 4.5 (legacy)'),
    ], string='Model', default='claude-sonnet-5-5', required=True)
    custom_model = fields.Char(
        string='Custom Model ID',
        help='Optional: any Anthropic model ID (e.g. a newer release). Overrides "Model".')
    use_prompt_cache = fields.Boolean(
        string='Prompt Caching', default=True,
        help='Cache the large system prompt (Odoo schema) between messages: lower cost and '
             'faster replies.')
    # ── Cost saving ────────────────────────────────────────────────────────
    local_mode = fields.Boolean(
        string='Answer Locally When Possible', default=True,
        help='Quick actions and simple requests ("show customers", "how many invoices", '
             '"install crm module"…) are answered directly by Odoo – no API call, 0 tokens.')
    cache_enabled = fields.Boolean(
        string='Re-use Previous Answers', default=True,
        help='When a question was already answered by Claude with a read-only query, the same '
             'question re-runs that query locally on fresh data instead of calling the API.')
    cache_ttl_days = fields.Integer(string='Cache Lifetime (days)', default=30)
    price_per_mtok = fields.Float(
        string='Blended Price per 1M Tokens (USD)', default=6.0,
        help='Used only to estimate the money saved (input+output average of your model).')
    stat_api_calls = fields.Integer(string='Claude API Calls', readonly=True)
    stat_api_tokens = fields.Integer(string='Tokens Used', readonly=True)
    stat_local = fields.Integer(string='Answered Locally', readonly=True)
    stat_cache = fields.Integer(string='Answered from Cache', readonly=True)
    stat_tokens_saved = fields.Integer(string='Tokens Saved (est.)', compute='_compute_savings')
    stat_money_saved = fields.Float(string='Money Saved (est. USD)', compute='_compute_savings', digits=(16, 2))
    stat_saved_pct = fields.Float(string='Requests Without API (%)', compute='_compute_savings', digits=(16, 1))

    def _avg_tokens(self):
        self.ensure_one()
        return int(self.stat_api_tokens / self.stat_api_calls) if self.stat_api_calls else 3000

    def _compute_savings(self):
        for rec in self:
            avoided = rec.stat_local + rec.stat_cache
            rec.stat_tokens_saved = avoided * rec._avg_tokens()
            rec.stat_money_saved = rec.stat_tokens_saved / 1_000_000 * (rec.price_per_mtok or 0)
            total = avoided + rec.stat_api_calls
            rec.stat_saved_pct = (avoided * 100.0 / total) if total else 0.0

    def _bump(self, field, amount=1):
        """Concurrency-safe counter increment (no ORM write conflicts between users)."""
        assert field in ('stat_api_calls', 'stat_api_tokens', 'stat_local', 'stat_cache')
        self.env.cr.execute(
            f'UPDATE claude_config SET {field} = COALESCE({field}, 0) + %s WHERE id = %s',
            (int(amount or 0), self.id))
        self.invalidate_recordset([field])

    def savings_summary(self):
        self.ensure_one()
        return {
            'api_calls': self.stat_api_calls, 'local': self.stat_local, 'cache': self.stat_cache,
            'tokens_saved': self.stat_tokens_saved, 'money_saved': round(self.stat_money_saved, 2),
            'saved_pct': round(self.stat_saved_pct, 1),
        }

    def action_clear_cache(self):
        self.env['claude.query.cache'].sudo().search([]).unlink()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'message': 'Answer cache cleared.', 'type': 'success', 'sticky': False}}

    def action_reset_stats(self):
        self.write({'stat_api_calls': 0, 'stat_api_tokens': 0, 'stat_local': 0, 'stat_cache': 0})

    confirm_deletes = fields.Boolean(
        string='Always Confirm Deletes', default=True,
        help='Deletions proposed by Claude always need an explicit click, even when '
             '"Confirm Write Operations" is off.')
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

    def _effective_model(self):
        self.ensure_one()
        return (self.custom_model or '').strip() or self.model_name or 'claude-sonnet-5-5'

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
            client = anthropic.Anthropic(api_key=api_key,
                                         timeout=float(self.request_timeout or 60))
            msg = client.messages.create(
                model=self._effective_model(),
                max_tokens=16,
                messages=[{'role': 'user', 'content': 'Reply with: OK'}],
            )
            reply = ''.join(getattr(b, 'text', '') for b in (msg.content or [])
                            if getattr(b, 'type', '') == 'text').strip() or '(no response)'
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
