"""Configuration Settings for AI Chat"""

import json
import logging
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    """Extend Settings to add AI Chat configuration"""

    _inherit = 'res.config.settings'

    # OpenRouter Configuration
    openrouter_api_key = fields.Char(
        string='OpenRouter API Key',
        config_parameter='odoo_ai_chat.openrouter_api_key',
        help='Your OpenRouter API key from https://openrouter.ai/keys'
    )

    openrouter_model = fields.Selection(
        selection='_get_available_models',
        string='AI Model',
        config_parameter='odoo_ai_chat.openrouter_model',
        default='openai/gpt-3.5-turbo',
        help='Model to use for AI responses'
    )

    openrouter_models_last_update = fields.Datetime(
        string='Models Last Updated',
        compute='_compute_models_last_update',
        help='Last time the model list was fetched from OpenRouter'
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
    ai_system_prompt = fields.Char(
        string='System Prompt',
        config_parameter='odoo_ai_chat.system_prompt',
        default='''You are a helpful AI assistant integrated into Odoo ERP system.
You can help users with their work by answering questions, providing information,
and when authorized, interacting with Odoo data using available tools.

Be concise, professional, and helpful. Always consider the context of working
within an enterprise resource planning system.

IMPORTANT: When users request multiple related tasks (e.g., "create stages, tasks, and tags"),
use multiple tool calls in a single response to complete everything efficiently. Don't stop
after each individual task - batch related operations together and provide a comprehensive
summary when done.

IMPORTANT Tool Usage Guidelines:

DATA RETRIEVAL (use search_records):
- Queries: "how many orders?", "what's the sum?", "list all products"
- Checking status: "what state are the orders?"
- Getting information: "show me customers", "find invoices"
- Returns data you can analyze and present to the user

DATA MODIFICATION (use write_record):
- Mark/update status: "mark orders as sent" → write_record with values={"state": "sent"}
- Change fields: "update the price", "set the status"
- Modify records: "mark as done", "change the name"
- IMPORTANT: Always provide values parameter as a dict

VISUALIZATION (use generate_graph):
- ONLY when user explicitly asks with keywords: "chart", "graph", "plot", "visualize", "show me a chart"
- NOT for: sums, counts, queries, status checks, or when user just wants numbers

CREATE (use create_record):
- Creating new records: "create an order", "add a new customer"
- For bulk creation tasks, call this tool multiple times in one response

After completing tool calls, ALWAYS provide a clear summary of what was accomplished.''',
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
    def _get_available_models(self):
        """Get list of available models from cache or default list"""
        ICP = self.env['ir.config_parameter'].sudo()
        cached_models = ICP.get_param('odoo_ai_chat.cached_models', '[]')

        try:
            models_data = json.loads(cached_models)
            if models_data:
                # Return cached models
                return [(model['id'], model['name']) for model in models_data]
        except (json.JSONDecodeError, KeyError):
            _logger.warning("Failed to parse cached models")

        # Return default popular models if cache is empty
        return [
            ('openai/gpt-4', 'OpenAI: GPT-4'),
            ('openai/gpt-4-turbo', 'OpenAI: GPT-4 Turbo'),
            ('openai/gpt-3.5-turbo', 'OpenAI: GPT-3.5 Turbo'),
            ('anthropic/claude-3-opus', 'Anthropic: Claude 3 Opus'),
            ('anthropic/claude-3-sonnet', 'Anthropic: Claude 3 Sonnet'),
            ('anthropic/claude-3-haiku', 'Anthropic: Claude 3 Haiku'),
            ('google/gemini-pro', 'Google: Gemini Pro'),
            ('meta-llama/llama-3-70b-instruct', 'Meta: Llama 3 70B'),
            ('mistralai/mistral-large', 'Mistral: Large'),
        ]

    @api.depends('openrouter_api_key')
    def _compute_models_last_update(self):
        """Compute when models were last updated"""
        ICP = self.env['ir.config_parameter'].sudo()
        last_update = ICP.get_param('odoo_ai_chat.models_last_update', False)

        for record in self:
            if last_update:
                record.openrouter_models_last_update = last_update
            else:
                record.openrouter_models_last_update = False

    def action_refresh_models(self):
        """Fetch latest models from OpenRouter API"""
        self.ensure_one()

        if not self.openrouter_api_key:
            raise UserError(_("Please configure your OpenRouter API key first."))

        try:
            # Fetch models from OpenRouter API
            url = "https://openrouter.ai/api/v1/models"
            headers = {
                "Authorization": f"Bearer {self.openrouter_api_key}",
            }

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            models_list = data.get('data', [])

            if not models_list:
                raise UserError(_("No models returned from OpenRouter API."))

            # Cache models with id and name
            cached_models = []
            for model in models_list:
                model_id = model.get('id', '')
                model_name = model.get('name', model_id)

                # Create a friendly display name
                if model_name == model_id:
                    # If name equals id, try to make it more readable
                    parts = model_id.split('/')
                    if len(parts) == 2:
                        provider = parts[0].replace('-', ' ').title()
                        model_part = parts[1].replace('-', ' ').title()
                        model_name = f"{provider}: {model_part}"

                cached_models.append({
                    'id': model_id,
                    'name': model_name,
                })

            # Sort by name
            cached_models.sort(key=lambda x: x['name'])

            # Store in config parameters
            ICP = self.env['ir.config_parameter'].sudo()
            ICP.set_param('odoo_ai_chat.cached_models', json.dumps(cached_models))
            ICP.set_param('odoo_ai_chat.models_last_update', fields.Datetime.now())

            # Invalidate cache to force recomputation of selection field
            self.env['ir.config_parameter'].invalidate_cache()
            self.invalidate_cache()

            # Return notification
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Successfully fetched %d models from OpenRouter API.  ') % len(cached_models),
                    'type': 'success',
                    'sticky': False,
                }
            }

        except requests.exceptions.RequestException as e:
            _logger.error("Failed to fetch models from OpenRouter: %s", str(e))
            raise UserError(_("Failed to fetch models from OpenRouter: %s") % str(e))
        except Exception as e:
            _logger.error("Error processing OpenRouter models: %s", str(e))
            raise UserError(_("Error processing models: %s") % str(e))

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
