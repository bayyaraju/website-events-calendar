# -*- coding: utf-8 -*-
{
    'name': 'WooCommerce Odoo Connector V19',
    'version': '19.0.1.0.0',
    'category': 'eCommerce/Connectors',
    'summary': 'Sync WooCommerce with Odoo 19 — orders, products, stock, customers, coupons, taxes + analytics dashboard.',
    'description': """
WooCommerce Odoo Connector
==========================
Full-featured connector between WooCommerce and Odoo V19.

Features:
- Analytics dashboard (OWL 2 + pure-canvas charts)
- Multi-store support
- Bidirectional product sync
- Order / customer / coupon / tax / stock sync
- Real-time webhook support
- Cron-based fallback sync
- Smart retry queue with logging
    """,
    'author': 'Rajashekar B',
    'website': '',
    'license': 'OPL-1',
    'price': 250.0,
    'currency': 'USD',
    'depends': [
        'sale_management',
        'stock',
        'account',
        'mail',
        'product',
        'delivery',
        'base_setup',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'data/mail_template_data.xml',
        'views/woo_dashboard_views.xml',
        'views/woo_instance_views.xml',
        'views/woo_product_views.xml',
        'views/woo_category_views.xml',
        'views/woo_order_views.xml',
        'views/woo_coupon_views.xml',
        'views/woo_customer_views.xml',
        'views/woo_log_views.xml',
        'views/woo_queue_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu_views.xml',
        'wizard/woo_sync_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'woo_connector/static/src/xml/woo_dashboard.xml',
            'woo_connector/static/src/js/woo_dashboard.js',
            'woo_connector/static/src/css/woo_connector.css',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'auto_install': False,
    'application': True,
}
