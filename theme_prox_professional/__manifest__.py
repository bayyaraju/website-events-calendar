# -*- coding: utf-8 -*-
{
    'name': 'Prox Professional Theme',
    'version': "19.0.1.0.0",
    'category': "Themes/Backend",
    'summary': 'Prox Professional Theme for Odoo 19',
    'description': """
                Prox Professional Theme for Odoo 19
                =====================================
                A framework-level UI overhaul inspired by Swiss financial design precision
                (Bloomberg Terminal × modern fintech — Stripe, Linear, Notion).
                
                Uses the correct Odoo 19 SCSS bundle hierarchy:
                  web._assets_primary_variables  → Odoo $o-* variable overrides
                  web._assets_backend_helpers    → Bootstrap variable overrides (prepend)
                  web.assets_backend             → Visual theme CSS (append)
                
                Features:
                - Instrument Serif (italic display) + Syne (UI labels) + DM Mono (numbers/data)
                - Warm parchment background (#F4F3EF) with deep navy accent (#1A3A5C)
                - Premium dark navbar (#0f1117) with gold brand accent (#c9a84c)
                - Refined stat cards, list tables, kanban cards with left-accent hover bars
                - Purchase/RFQ list: professional badge system, monospace amounts, row animations
                - AJAX progress bar, Ctrl+/ search shortcut
                - Smooth view animations (prefers-reduced-motion respected)
                - No dark/light mode toggle — single canonical professional theme
    """,
    'author': 'Rajashekar B',
    'website': '',
    'license': 'OPL-1',
    'price': 55.0,
    'currency': 'USD',
    'depends': ['base', 'web'],

    'data': [
        'views/webclient_templates.xml',
    ],

    'assets': {

        # ── 1. EARLIEST: override Odoo's own $o-* SCSS variables ──────────────
        'web._assets_primary_variables': [
            ('prepend', 'theme_prox_professional/static/src/scss/primary_variables.scss'),
        ],

        # ── 2. NEXT: Bootstrap variable overrides (before BS compilation) ─────
        'web._assets_backend_helpers': [
            ('prepend', 'theme_prox_professional/static/src/scss/bootstrap_overridden.scss'),
        ],

        # ── 3. LAST: Visual theme CSS (after all Odoo + Bootstrap CSS) ────────
        'web.assets_backend': [
            ('append', 'theme_prox_professional/static/src/scss/theme.scss'),
            ('append', 'theme_prox_professional/static/src/js/backend_enhancements.js'),
        ],
    },

    'installable': True,
    'application': True,
    'support': 'raj.odoo2026@gmail.com',
}
