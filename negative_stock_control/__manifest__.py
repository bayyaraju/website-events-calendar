# -*- coding: utf-8 -*-
{
    'name': 'Advanced Inventory Control & Negative Stock Prevention Engine',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Enterprise-level negative stock prevention with smart blocking, role-based overrides, analytics, and real-time monitoring',
    'description': """
Advanced Inventory Control & Negative Stock Prevention Engine
=============================================================

🚀 Enterprise Features:
- Smart Blocking Levels: Allow / Warn Only / Strict Block per warehouse
- Product & Category-level negative stock configuration
- Role-based override with mandatory reason logging & audit trail
- Real-time stock calculation (On Hand / Available / Forecasted)
- Warehouse-level control panel
- Negative Stock Alert Dashboard
- Scheduled monitor with email alerts
- Sale Order soft-lock warnings
- Override analytics & penalty tracking
- Multi-company safe

Perfect for production, transit, and service warehouses.
    """,
    'author': 'Rajashekar B',
    'website': '',
    'license': 'OPL-1',
    'price': 25.0,
    'currency': 'USD',
    'depends': [
        'stock',
        'sale_stock',
        'purchase_stock',
        'mail',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/cron.xml',
        'data/mail_template.xml',
        'views/res_config_settings_views.xml',
        'views/stock_warehouse_views.xml',
        'views/product_views.xml',
        'views/product_category_views.xml',
        'views/negative_stock_log_views.xml',
        'views/negative_stock_dashboard_views.xml',
        'wizard/stock_override_wizard_views.xml',
        'views/menu_views.xml',
        'report/negative_stock_report.xml',
        'report/negative_stock_report_template.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'negative_stock_control/static/src/css/dashboard.css',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
