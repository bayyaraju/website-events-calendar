# -*- coding: utf-8 -*-
from odoo import models, fields, api


class EventEvent(models.Model):
    _inherit = 'event.event'

    calendar_color = fields.Char(
        string='Calendar Color',
        compute='_compute_calendar_color',
        store=False,
        help='Color used to display the event in the calendar view'
    )

    @api.depends('event_type_id')
    def _compute_calendar_color(self):
        """Compute a color for the event based on its type."""
        color_palette = [
            '#E63946', '#2A9D8F', '#E9C46A', '#F4A261',
            '#264653', '#6A4C93', '#1982C4', '#8AC926',
            '#FF595E', '#6A994E', '#BC6C25', '#0077B6',
        ]
        for record in self:
            if record.event_type_id and record.event_type_id.id:
                color_idx = record.event_type_id.id % len(color_palette)
                record.calendar_color = color_palette[color_idx]
            else:
                record.calendar_color = color_palette[0]
