# -*- coding: utf-8 -*-
{
    'name': 'Enterprise Workflow Engine',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Enterprise-grade visual workflow engine for Odoo 19',
    'description': """
Enterprise Workflow Engine
==========================
A production-ready, enterprise-grade workflow automation engine featuring:

- Visual drag-and-drop workflow designer (OWL-based canvas)
- Dynamic multi-step process management with versioning
- Conditional branching and parallel execution gates
- Multi-level approval chains (single / any / all / majority / sequential)
- SLA enforcement with configurable escalation actions
- Automated triggers (on create, write, cron, webhook)
- Full immutable audit trail per instance
- Role-based access control (User / Designer / Manager)
- REST API + Webhook endpoints
- Sub-workflow support
- Dashboard & pivot analytics
- Mixin to add workflow support to any Odoo model
""",
    'author': 'Rajashekar B',
    'license': 'OPL-1',
    'price': 10.0,
    'currency': 'USD',
    'depends': ['base', 'mail', 'web', 'base_automation'],
    'data': [
        'security/ir_groups.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'data/ir_cron.xml',
        'views/workflow_definition_views.xml',
        'views/workflow_stage_views.xml',
        'views/workflow_transition_views.xml',
        'views/workflow_action_views.xml',
        'views/workflow_sla_views.xml',
        'views/workflow_instance_views.xml',
        'views/workflow_approval_views.xml',
        'views/workflow_log_views.xml',
        'views/menu_views.xml',
        'wizard/trigger_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'enterprise_workflow/static/src/css/designer.css',
            'enterprise_workflow/static/src/xml/designer.xml',
            'enterprise_workflow/static/src/js/designer.js',
        ],
    },
    'demo': [
        'data/demo.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
