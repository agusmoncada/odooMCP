"""Configuration Settings for AI Chat"""

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Extend Settings to add AI Chat configuration"""

    _inherit = 'res.config.settings'

    # OpenRouter Configuration
    openrouter_api_key = fields.Char(
        string='OpenRouter API Key',
        config_parameter='odoo_ai_chat.openrouter_api_key',
        help='Your OpenRouter API key from https://openrouter.ai/keys'
    )

    openrouter_model = fields.Char(
        string='AI Model',
        config_parameter='odoo_ai_chat.openrouter_model',
        default='openai/gpt-3.5-turbo',
        help='Model to use for AI responses (e.g., openai/gpt-3.5-turbo, anthropic/claude-3-sonnet)'
    )

    openrouter_temperature = fields.Float(
        string='Temperature',
        config_parameter='odoo_ai_chat.openrouter_temperature',
        default=0.7,
        help='Controls randomness: 0 is focused, 2 is very creative'
    )

    openrouter_max_tokens = fields.Integer(
        string='Max Tokens',
        config_parameter='odoo_ai_chat.openrouter_max_tokens',
        default=2000,
        help='Maximum tokens to generate in responses'
    )

    # MCP Configuration
    mcp_tools_enabled = fields.Boolean(
        string='Enable MCP Tools',
        config_parameter='odoo_ai_chat.mcp_tools_enabled',
        default=True,
        help='Allow AI to use MCP tools to interact with Odoo data'
    )

    # System Prompt
    ai_system_prompt = fields.Text(
        string='System Prompt',
        config_parameter='odoo_ai_chat.system_prompt',
        default='''You are a helpful AI assistant integrated into Odoo ERP system.
You can help users with their work by answering questions, providing information,
and when authorized, interacting with Odoo data using available tools.

Be concise, professional, and helpful. Always consider the context of working
within an enterprise resource planning system.''',
        help='System prompt that defines the AI assistant behavior'
    )

    # Site Configuration for OpenRouter
    site_url = fields.Char(
        string='Site URL',
        config_parameter='odoo_ai_chat.site_url',
        default='',
        help='Your site URL for OpenRouter attribution'
    )

    site_name = fields.Char(
        string='Site Name',
        config_parameter='odoo_ai_chat.site_name',
        default='Odoo AI Chat',
        help='Your site name for OpenRouter attribution'
    )

    @api.model
    def get_ai_config(self):
        """Get AI configuration for use in controllers"""
        ICP = self.env['ir.config_parameter'].sudo()

        return {
            'api_key': ICP.get_param('odoo_ai_chat.openrouter_api_key', ''),
            'model': ICP.get_param('odoo_ai_chat.openrouter_model', 'openai/gpt-3.5-turbo'),
            'temperature': float(ICP.get_param('odoo_ai_chat.openrouter_temperature', '0.7')),
            'max_tokens': int(ICP.get_param('odoo_ai_chat.openrouter_max_tokens', '2000')),
            'mcp_tools_enabled': ICP.get_param('odoo_ai_chat.mcp_tools_enabled', 'True') == 'True',
            'system_prompt': ICP.get_param(
                'odoo_ai_chat.system_prompt',
                'You are a helpful AI assistant integrated into Odoo.'
            ),
            'site_url': ICP.get_param('odoo_ai_chat.site_url', ''),
            'site_name': ICP.get_param('odoo_ai_chat.site_name', 'Odoo AI Chat'),
        }
