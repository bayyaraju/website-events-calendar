# -*- coding: utf-8 -*-
import json
from odoo import http, fields
from odoo.http import request
from odoo.addons.website_event.controllers.main import WebsiteEventController


COLOR_PALETTE = [
    '#E63946', '#2A9D8F', '#E9C46A', '#F4A261',
    '#264653', '#6A4C93', '#1982C4', '#8AC926',
    '#FF595E', '#6A994E', '#BC6C25', '#0077B6',
]


def _event_color(event):
    if event.event_type_id and event.event_type_id.id:
        return COLOR_PALETTE[event.event_type_id.id % len(COLOR_PALETTE)]
    return COLOR_PALETTE[0]


def _get_event_url(event):
    """Return /event/<slug>/register URL."""
    try:
        slug = event.website_slug
        if slug:
            return '/event/%s/register' % slug
    except AttributeError:
        pass
    return '/event/%d/register' % event.id


def _build_events_json(events):
    """Return a JSON string safe to embed in an HTML data-attribute."""
    result = []
    for event in events:
        try:
            location = ''
            if event.address_id:
                location = event.address_id.city or event.address_id.name or ''
        except Exception:
            location = ''

        try:
            is_limited = (
                event.seats_limited
                if hasattr(event, 'seats_limited')
                else getattr(event, 'seats_availability', '') == 'limited'
            )
            seats = int(event.seats_available) if is_limited else -1
        except Exception:
            seats = -1

        try:
            type_id = event.event_type_id.id if event.event_type_id else 0
            type_name = event.event_type_id.name if event.event_type_id else 'General'
        except Exception:
            type_id = 0
            type_name = 'General'

        result.append({
            'id': event.id,
            'title': event.name or '',
            'start': event.date_begin.strftime('%Y-%m-%dT%H:%M:%S') if event.date_begin else '',
            'end': event.date_end.strftime('%Y-%m-%dT%H:%M:%S') if event.date_end else '',
            'color': _event_color(event),
            'url': _get_event_url(event),
            'extendedProps': {
                'location': location,
                'type': type_name,
                'typeId': type_id,
                'seats': seats,
            }
        })

    return json.dumps(result, ensure_ascii=False)


def _published_domain():
    """Return the correct published domain for the installed Odoo version."""
    EventEvent = request.env['event.event']
    if 'is_published' in EventEvent._fields:
        return [('is_published', '=', True)]
    if 'website_published' in EventEvent._fields:
        return [('website_published', '=', True)]
    # Fallback: no published filter if field not found
    return []


class WebsiteEventsCalendarController(WebsiteEventController):

    @http.route(['/events/calendar'],
                type='http', auth='public', website=True, sitemap=True)
    def events_calendar(self, type=None, **post):
        """Render the events calendar page."""
        EventType = request.env['event.type'].sudo()
        EventEvent = request.env['event.event'].sudo()

        event_types = EventType.search([], order='name asc')

        current_type = 0
        if type:
            try:
                current_type = int(type)
            except (ValueError, TypeError):
                current_type = 0

        domain = _published_domain()
        if current_type:
            domain += [('event_type_id', '=', current_type)]

        all_events = EventEvent.search(domain, order='date_begin asc', limit=500)
        events_count = len(all_events)

        today = fields.Datetime.now()
        upcoming_events = EventEvent.search(
            domain + [('date_begin', '>=', today)],
            order='date_begin asc',
            limit=5
        )

        type_colors = {t.id: COLOR_PALETTE[t.id % len(COLOR_PALETTE)] for t in event_types}

        values = {
            'event_types': event_types,
            'events_count': events_count,
            'upcoming_events': upcoming_events,
            'type_colors': type_colors,
            'current_type': current_type,
            'events_json': _build_events_json(all_events),
            'main_object': request.website,
            'get_event_url': _get_event_url,
        }

        return request.render('website_events_calendar.events_calendar_page', values)
