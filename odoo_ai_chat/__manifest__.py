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
        * OpenRouter AI provider connectivity with multiple AI models
        * Chat interface accessible from anywhere in Odoo
        * Chat history management with session support
        * Configurable AI settings (model, temperature, system prompt)
        * Graph/chart generation from Odoo data
        * PDF invoice processing and automatic vendor bill creation
        * Tool calling for AI-Odoo data interaction
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'images': ['static/description/icon.png'],
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/ai_chat_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # External libraries
            'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
            # JavaScript
            'odoo_ai_chat/static/src/js/chart_renderer.js',
            'odoo_ai_chat/static/src/js/ai_chat_service.js',
            'odoo_ai_chat/static/src/js/ai_chat_widget.js',
            'odoo_ai_chat/static/src/js/systray_item.js',
            # CSS
            'odoo_ai_chat/static/src/css/ai_chat.css',
            # Templates
            'odoo_ai_chat/static/src/xml/ai_chat_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
