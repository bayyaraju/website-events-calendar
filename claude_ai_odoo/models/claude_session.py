# -*- coding: utf-8 -*-
import json
from odoo import models, fields


class ClaudeSession(models.Model):
    _name = 'claude.session'
    _description = 'Claude AI Chat Session'
    _order = 'create_date desc'

    user_id = fields.Many2one('res.users', string='User', default=lambda s: s.env.uid, readonly=True)
    config_id = fields.Many2one('claude.config', string='Config', readonly=True)
    history_json = fields.Text(default='[]')
    total_tokens = fields.Integer(default=0, readonly=True)
    state = fields.Selection([('active', 'Active'), ('closed', 'Closed')], default='active')
    message_ids = fields.One2many('claude.message', 'session_id', string='Messages')

    def get_history(self):
        try:
            return json.loads(self.history_json or '[]')
        except Exception:
            return []

    def add_message(self, role, content):
        history = self.get_history()
        history.append({'role': role, 'content': content})
        # Keep last 40 messages to avoid token overflow
        if len(history) > 40:
            history = history[-40:]
        self.history_json = json.dumps(history)

    def action_clear(self):
        self.write({'history_json': '[]', 'total_tokens': 0})
        self.message_ids.unlink()

    def action_close(self):
        self.write({'state': 'closed'})


class ClaudeMessage(models.Model):
    _name = 'claude.message'
    _description = 'Claude AI Message'
    _order = 'id asc'

    session_id = fields.Many2one('claude.session', ondelete='cascade')
    role = fields.Selection([('user', 'User'), ('assistant', 'Claude')], required=True)
    content = fields.Text(required=True)
    tokens = fields.Integer(default=0)
    create_date = fields.Datetime(readonly=True)
