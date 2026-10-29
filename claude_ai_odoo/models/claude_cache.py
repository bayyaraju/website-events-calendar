# -*- coding: utf-8 -*-
from odoo import fields, models


class ClaudeQueryCache(models.Model):
    """Questions already answered by Claude with a read-only query. When the same
    question is asked again, the stored query is re-executed locally on fresh data –
    no API call, no tokens."""
    _name = 'claude.query.cache'
    _description = 'Claude AI Query Cache'
    _order = 'write_date desc'
    _rec_name = 'question'

    key = fields.Char(required=True, index=True)
    question = fields.Char(required=True)
    title = fields.Char()
    op_json = fields.Text(string='Query')
    chart_type = fields.Char()
    excel_json = fields.Text(string='Excel Spec')
    hits = fields.Integer(default=0, readonly=True)

    _key_uniq = models.Constraint('UNIQUE(key)', 'Question already cached.')
