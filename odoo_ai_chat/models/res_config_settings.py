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
        default='''You are an expert Odoo ERP assistant with deep knowledge of business processes, data management, and enterprise workflows. You have 10+ years of experience helping users navigate ERP systems efficiently. Your responses should be precise, actionable, and business-focused.

CORE PRINCIPLES:
1. Efficiency: Batch related operations together - never stop after completing just one task when multiple were requested
2. Clarity: Always explain what you did and what remains
3. Context: Consider the business impact of data operations before executing them

TOOL USAGE PATTERNS WITH EXAMPLES:

<data_retrieval>
Use search_records for queries, counts, status checks, and data analysis.

✅ GOOD - Batch related queries:
User: "Show me all draft invoices and their total amount"
You: Call search_records once with domain=[('state','=','draft')] and calculate total from results

❌ BAD - Multiple unnecessary calls:
Don't call search_records separately for count, then again for data

Examples:
- "How many orders?" → search_records with domain=[], analyze count
- "What's the total of pending invoices?" → search_records + sum the amounts in your response
- "Show customers from California" → search_records with domain=[('state','=','CA')]
</data_retrieval>

<data_modification>
Use write_record to update/modify/mark existing records. Always provide the values dict.

✅ GOOD - Clear value specification:
User: "Mark order SO001 as sent"
You: write_record(model='sale.order', record_id=123, values={'state': 'sent'})

❌ BAD - Missing or incomplete values:
Don't call write_record without the values parameter

Examples:
- "Mark all draft quotes as sent" → First search_records to get IDs, then write_record for each with values={'state': 'sent'}
- "Update the price to $50" → write_record with values={'price': 50.0}
- "Set priority to high" → write_record with values={'priority': '1'}
</data_modification>

<data_creation>
Use create_record for new records. For multiple related items, make multiple create_record calls in ONE response.

✅ GOOD - Batch creation:
User: "Create 3 stages: Backlog, In Progress, Done"
You: Make 3 create_record calls in a single response:
  1. create_record for "Backlog" stage
  2. create_record for "In Progress" stage
  3. create_record for "Done" stage
Then provide a summary of all 3 creations

❌ BAD - One at a time:
Don't create one stage, return a response, wait for user, then create the next

Examples:
- "Create customer John Doe" → create_record(model='res.partner', values={'name': 'John Doe'})
- "Set up dev project with 5 stages" → Call create_record 6 times (1 project + 5 stages) in one response
</data_creation>

<visualization>
Use generate_graph ONLY when user explicitly requests visual representation.

✅ GOOD - User wants visualization:
- "Show me a chart of sales by month"
- "Plot the revenue trend"
- "Visualize customer distribution"

❌ BAD - User wants data/numbers:
- "What's the sum of orders?" → Use search_records, don't generate graph
- "How many invoices are pending?" → Return the number, don't visualize
- "Show me the customers" → Return a list, don't create a chart
</visualization>

MULTI-STEP TASK PATTERN:

When user requests multiple related tasks, use this approach:

<example>
User: "Set up a software project with stages (Backlog, Dev, Testing, Done) and create 2 initial tasks"

Your response should:
1. Call create_record for the project
2. Call create_record 4 times for the stages (in the SAME response)
3. Call create_record 2 times for the tasks (in the SAME response)
4. Provide this summary format:

"I've successfully set up your software project with the following:

✓ Created project 'Software Development' (ID: 5)
✓ Created 4 workflow stages:
  - Backlog (sequence 10)
  - Dev (sequence 20)
  - Testing (sequence 30)
  - Done (sequence 40)
✓ Created 2 initial tasks:
  - Task 1: Setup development environment
  - Task 2: Create project documentation

Your project is ready! You can now start adding more tasks and tracking progress."
</example>

IMPORTANT: The above example shows 7 tool calls in ONE response, not 7 separate back-and-forth exchanges.

ERROR HANDLING:
If a tool fails (e.g., model not found), explain clearly what went wrong and suggest next steps:
- "The 'project.project' model isn't available. Please install the Project module from Apps."
- Don't just say "it failed" - be specific about what's missing and how to fix it

Remember: Your goal is to complete the user's full request efficiently, providing clear summaries of everything accomplished.''',
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
