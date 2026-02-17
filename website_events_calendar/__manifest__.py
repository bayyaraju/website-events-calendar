# -*- coding: utf-8 -*-
{
    'name': 'Website Events Calendar View',
    'version': '19.0.2.0.0',
    'category': 'Website/Events',
    'summary': 'Interactive calendar view for published events on website',
    'description': """
        Website Events Calendar View (v2 - Professional UI)
        ====================================================
        Adds a beautiful, fully responsive dark-themed interactive calendar
        to your Odoo 19 website events.

        Features:
        * Monthly, weekly and agenda (list) calendar views via FullCalendar 6
        * Hover tooltip with event details, type badge, color accent bar, seats
        * Dark glass-morphism UI with DM Serif Display editorial typography
        * Sidebar: view toggle, filter by event type, upcoming events list
        * Color-coded events by type (12-color professional palette)
        * Fully responsive layout from mobile to 4K
        * Graceful scrollable sidebar sections
        * Seamless Odoo 19 integration via website_event
    """,
    'author': 'Rajashekar B',
    'website': '',
    'license': 'OPL-1',
    'price': 25.0,
    'currency': 'USD',
    'depends': [
        'website',
        'website_event',
        'event',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/event_views.xml',
        'templates/calendar_template.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_events_calendar/static/src/css/calendar.css',
            'website_events_calendar/static/src/js/calendar.js',
        ],
    },
    'images': [
        'static/description/main_screenshot.png',
        'static/description/calender_view_btn.png',
        'static/description/agenda_view.png',
        'static/description/weekly_view.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'support': 'raj.odoo2026@gmail.com',

}
