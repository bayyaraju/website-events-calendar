# -*- coding: utf-8 -*-
{
    'name': 'Claude AI Assistant / Chat Assistant',
    'version': '19.0.5.1.0',
    'category': 'Extra Tools',
    'summary': 'Claude AI: Query, Create, Update, Delete, Charts & Excel — Full CRUD via Natural Language',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/claude_security.xml',
        'security/ir.model.access.csv',
        'views/claude_config_view.xml',
        'views/claude_session_view.xml',
        'views/claude_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'claude_ai_odoo/static/src/css/claude_chat.css',
            'claude_ai_odoo/static/src/xml/claude_chat.xml',
            'claude_ai_odoo/static/src/js/claude_chat.js',
        ],
    },
    'images': ['static/description/icon.png'],
    'post_init_hook': 'post_init_hook',
    'author': 'Rajashekar B',
    'website': '',
    'license': 'OPL-1',
    'price': 35.0,
    'currency': 'USD',
    'installable': True,
    'application': True,
    'auto_install': False,
    'support': 'raj.odoo2026@gmail.com',
}
