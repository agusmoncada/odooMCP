"""Mail Channel Extension for AI Integration"""

from odoo import api, fields, models
import logging
import json
import requests

_logger = logging.getLogger(__name__)


class MailChannel(models.Model):
    """Extend mail.channel to integrate AI Assistant"""

    _inherit = 'mail.channel'

    is_ai_channel = fields.Boolean(
        string='AI Channel',
        default=False,
        help='This channel is connected to an AI Assistant'
    )

    ai_session_id = fields.Many2one(
        'ai.chat.session',
        string='AI Session',
        help='Linked AI chat session for this channel'
    )

    @api.model
    def create(self, vals):
        """Mark channels with AI bot as AI channels"""
        channel = super().create(vals)

        # If channel is already marked as AI channel and has a session, skip
        if channel.is_ai_channel and channel.ai_session_id:
            return channel

        # Check if channel includes AI bot partner and mark as AI channel
        ai_bot = self.env['res.partner'].sudo().search([
            ('name', '=', 'AI Assistant Bot'),
            ('email', '=', 'ai.assistant@odoo.local')
        ], limit=1)

        if ai_bot and ai_bot.id in channel.channel_partner_ids.ids:
            if not channel.is_ai_channel:
                channel.is_ai_channel = True

            # Create linked AI session if not already linked
            if not channel.ai_session_id:
                session = self.env['ai.chat.session'].create({
                    'name': channel.name or 'AI Assistant Chat',
                    'user_id': self.env.user.id,
                    'channel_id': channel.id,
                })
                channel.ai_session_id = session.id

        return channel

    def message_post(self, **kwargs):
        """Override to intercept messages to AI channels"""
        message = super().message_post(**kwargs)

        _logger.info(f"message_post called on channel {self.id} ({self.name}), is_ai_channel={self.is_ai_channel}, message_author_id={message.author_id.id if message.author_id else None}")

        # Check if this is an AI channel and message has an author
        # Skip processing if message has no author to prevent recursion
        if not self.is_ai_channel or not message.author_id:
            return message

        ai_bot = self.env['res.partner'].sudo().search([
            ('name', '=', 'AI Assistant Bot'),
            ('email', '=', 'ai.assistant@odoo.local')
        ], limit=1)

        _logger.info(f"AI channel detected, ai_bot={ai_bot.id if ai_bot else None}, message_author={message.author_id.id}")

        # Only process if message is from user, not from AI bot
        # Also skip if AI bot not found to prevent errors
        if ai_bot and message.author_id.id != ai_bot.id:
            _logger.info(f"Processing AI message from user")
            # Process AI message
            try:
                self._process_ai_message(message)
            except Exception as e:
                # Log the error without exc_info if it might cause recursion issues
                _logger.error(f"Error processing AI message: {str(e)}")

        return message

    def _process_ai_message(self, user_message):
        """Process user message and generate AI response"""
        try:
            # Get or create AI session for this channel
            if not self.ai_session_id:
                session = self.env['ai.chat.session'].create({
                    'name': self.name,
                    'user_id': self.env.user.id,
                    'channel_id': self.id,
                })
                self.ai_session_id = session.id
            else:
                session = self.ai_session_id

            # Create user message in session
            user_msg = self.env['ai.chat.message'].create({
                'session_id': session.id,
                'role': 'user',
                'content': user_message.body if hasattr(user_message, 'body') else str(user_message),
            })

            # Get AI configuration
            config_params = self.env['ir.config_parameter'].sudo()
            openrouter_api_key = config_params.get_param('odoo_ai_chat.openrouter_api_key')
            openrouter_model = config_params.get_param('odoo_ai_chat.openrouter_model', 'openai/gpt-3.5-turbo')

            if not openrouter_api_key:
                raise ValueError("OpenRouter API key not configured")

            # Build context-aware system prompt
            system_prompt = self._build_context_aware_prompt()

            # Get messages for API
            messages = session.get_messages_for_api()

            # Add system prompt
            messages.insert(0, {
                'role': 'system',
                'content': system_prompt
            })

            # Get MCP tools if enabled
            tools = None
            mcp_enabled = config_params.get_param('odoo_ai_chat.mcp_tools_enabled', 'True') == 'True'
            if mcp_enabled:
                try:
                    mcp_server = self.env['mcp.server'].sudo()
                    tools = mcp_server.get_tools()
                except Exception as e:
                    _logger.warning(f"Could not load MCP tools: {e}")

            # Call OpenRouter API
            response = self._call_openrouter_api(
                openrouter_api_key,
                openrouter_model,
                messages,
                tools
            )

            if response and response.get('choices'):
                assistant_message = response['choices'][0]['message']
                content = assistant_message.get('content', '')

                # Handle tool calls if any
                tool_calls = assistant_message.get('tool_calls')
                if tool_calls:
                    # Process tool calls...
                    self._process_tool_calls(session, tool_calls, content)
                else:
                    # Create assistant message
                    self.env['ai.chat.message'].create({
                        'session_id': session.id,
                        'role': 'assistant',
                        'content': content,
                    })

                    # Post AI response to channel
                    ai_bot = self.env['res.partner'].sudo().search([
                        ('name', '=', 'AI Assistant Bot')
                    ], limit=1)

                    if ai_bot:
                        self.message_post(
                            body=content,
                            author_id=ai_bot.id,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment'
                        )

        except Exception as e:
            _logger.error(f"Error processing AI message: {e}", exc_info=True)
            # Post error message to channel with AI bot as author to prevent recursion
            try:
                ai_bot = self.env['res.partner'].sudo().search([
                    ('name', '=', 'AI Assistant Bot')
                ], limit=1)

                if ai_bot:
                    self.with_context(mail_create_nosubscribe=True).message_post(
                        body=f"Sorry, I encountered an error: {str(e)}",
                        author_id=ai_bot.id,
                        message_type='notification'
                    )
            except Exception as post_error:
                # If even posting the error fails, just log it
                _logger.error(f"Failed to post error message to channel: {post_error}")

    def _build_context_aware_prompt(self):
        """Build context-aware system prompt"""
        config_params = self.env['ir.config_parameter'].sudo()
        base_prompt = config_params.get_param('odoo_ai_chat.system_prompt', 'You are a helpful AI assistant integrated with Odoo.')

        # Get user context
        user = self.env.user
        context_parts = [base_prompt]

        # Add user language and timezone
        context_parts.append(f"""
USER CONTEXT:
- Name: {user.name}
- Language: {user.lang}
- Timezone: {user.tz}
- Company: {user.company_id.name if user.company_id else 'N/A'}

IMPORTANT: Please respond in the user's language ({user.lang}) unless explicitly asked otherwise.
If the user's language is Spanish (es_ES, es_MX, etc.), respond in Spanish.
If the user's language is French (fr_FR, etc.), respond in French.
And so on for other languages.
""")

        return "\n\n".join(context_parts)

    def _call_openrouter_api(self, api_key, model, messages, tools=None):
        """Call OpenRouter API"""
        url = "https://openrouter.ai/api/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
        }

        if tools:
            payload["tools"] = tools

        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        return response.json()

    def _process_tool_calls(self, session, tool_calls, assistant_content):
        """Process tool calls from AI"""
        # This is a simplified version - the full implementation would
        # execute tools via MCP server and handle responses
        _logger.info(f"Processing {len(tool_calls)} tool calls")

        # Create assistant message with tool calls
        tool_calls_data = []
        for tc in tool_calls:
            tool_calls_data.append({
                'tool_call_id': tc['id'],
                'name': tc['function']['name'],
                'arguments': json.loads(tc['function']['arguments'])
            })

        self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': assistant_content or '',
            'tool_calls': json.dumps(tool_calls_data),
        })

        # Execute tools and create tool response messages
        mcp_server = self.env['mcp.server'].sudo()

        for tc in tool_calls:
            try:
                tool_name = tc['function']['name']
                tool_args = json.loads(tc['function']['arguments'])

                result = mcp_server.call_tool(tool_name, tool_args)

                # Create tool response message
                self.env['ai.chat.message'].create({
                    'session_id': session.id,
                    'role': 'tool',
                    'content': json.dumps(result),
                    'tool_call_id': tc['id'],
                    'metadata': json.dumps({'tool_name': tool_name}),
                })

            except Exception as e:
                _logger.error(f"Error executing tool {tool_name}: {e}")
                # Create error response
                self.env['ai.chat.message'].create({
                    'session_id': session.id,
                    'role': 'tool',
                    'content': json.dumps({'error': str(e)}),
                    'tool_call_id': tc['id'],
                    'metadata': json.dumps({'tool_name': tool_name}),
                })

        # After tools execute, call AI again with tool results
        # This would trigger another API call to get the final response
        # For now, just notify the user
        ai_bot = self.env['res.partner'].sudo().search([
            ('name', '=', 'AI Assistant Bot')
        ], limit=1)

        if ai_bot:
            self.message_post(
                body="Processing your request with tools...",
                author_id=ai_bot.id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment'
            )
