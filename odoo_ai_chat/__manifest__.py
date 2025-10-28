{
    'name': 'AI Chat Assistant',
    'version': '16.0.1.0.0',
    'category': 'Productivity',
    'summary': 'AI-powered chat assistant with MCP server and OpenRouter integration',
    'description': """
        AI Chat Assistant for Odoo v16
        ================================

        This module provides:
        * MCP (Model Context Protocol) server integration
        * OpenRouter AI provider connectivity
        * Chat interface accessible from anywhere in Odoo
        * Chat history management
        * Configurable AI settings
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/ai_chat_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_ai_chat/static/src/js/ai_chat_service.js',
            'odoo_ai_chat/static/src/js/ai_chat_widget.js',
            'odoo_ai_chat/static/src/js/systray_item.js',
            'odoo_ai_chat/static/src/css/ai_chat.css',
            'odoo_ai_chat/static/src/xml/ai_chat_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
