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
        default='anthropic/claude-3-haiku',
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
        default=800,
        help='Maximum tokens to generate in responses'
    )

    # Conversation History Settings
    max_history_messages = fields.Integer(
        string='Max History Messages',
        config_parameter='odoo_ai_chat.max_history_messages',
        default=20,
        help='Maximum number of conversation messages to include in context (0 = unlimited)'
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
        default='''You are an expert Odoo ERP assistant. Be precise, actionable, and business-focused.

CORE PRINCIPLES:
1. Batch operations together - complete all requested tasks in one response
2. Explain what you did clearly
3. Consider business impact before executing data operations

TOOL USAGE:
- search_records: queries, counts, data analysis
- write_record: update existing records (always include values dict)
- create_record: new records (batch multiple creates in one response)
- generate_graph: ONLY when user explicitly requests visualization

MULTI-STEP TASKS:
Complete all related tasks in ONE response, then provide a clear summary.

ERROR HANDLING:
If tools fail, explain what went wrong and suggest specific fixes (e.g., "Install X module").''',
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

        # Return default models ordered by cost (cheapest first)
        return [
            # BUDGET MODELS (lowest cost)
            ('anthropic/claude-3-haiku', 'Anthropic: Claude 3 Haiku (Fastest & Cheapest)'),
            ('openai/gpt-3.5-turbo', 'OpenAI: GPT-3.5 Turbo (Budget)'),
            ('google/gemini-pro', 'Google: Gemini Pro (Budget)'),
            ('mistralai/mistral-7b-instruct', 'Mistral: 7B Instruct (Ultra Budget)'),
            ('meta-llama/llama-3-8b-instruct', 'Meta: Llama 3 8B (Ultra Budget)'),
            
            # BALANCED MODELS (moderate cost)
            ('anthropic/claude-3-sonnet', 'Anthropic: Claude 3 Sonnet (Balanced)'),
            ('openai/gpt-4o-mini', 'OpenAI: GPT-4o Mini (Balanced)'),
            ('meta-llama/llama-3-70b-instruct', 'Meta: Llama 3 70B (Balanced)'),
            
            # PREMIUM MODELS (higher cost)
            ('openai/gpt-4-turbo', 'OpenAI: GPT-4 Turbo (Premium)'),
            ('openai/gpt-4', 'OpenAI: GPT-4 (Premium)'),
            ('anthropic/claude-3-opus', 'Anthropic: Claude 3 Opus (Premium)'),
            ('mistralai/mistral-large', 'Mistral: Large (Premium)'),
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
            'model': ICP.get_param('odoo_ai_chat.openrouter_model', 'anthropic/claude-3-haiku'),
            'temperature': float(ICP.get_param('odoo_ai_chat.openrouter_temperature', '0.7')),
            'max_tokens': int(ICP.get_param('odoo_ai_chat.openrouter_max_tokens', '800')),
            'max_history_messages': int(ICP.get_param('odoo_ai_chat.max_history_messages', '20')),
            'mcp_tools_enabled': ICP.get_param('odoo_ai_chat.mcp_tools_enabled', 'True') == 'True',
            'system_prompt': ICP.get_param(
                'odoo_ai_chat.system_prompt',
                'You are a helpful AI assistant integrated into Odoo.'
            ),
            'site_url': ICP.get_param('odoo_ai_chat.site_url', ''),
            'site_name': ICP.get_param('odoo_ai_chat.site_name', 'Odoo AI Chat'),
        }
