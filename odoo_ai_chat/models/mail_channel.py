"""Mail Channel Extension for AI Integration"""

from odoo import api, fields, models
from odoo.tools import html_escape, plaintext2html
import logging
import json
import requests
import threading

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
            _logger.info(f"Processing AI message from user, starting async thread")
            # Get message content before starting thread (avoid cursor issues)
            message_body = message.body or ''
            _logger.info(f"Thread params: dbname={self.env.cr.dbname}, uid={self.env.uid}, channel_id={self.id}, message_body_length={len(message_body)}")
            # Process AI message asynchronously to avoid blocking the UI
            # Use threading to process in background with a new cursor
            thread = threading.Thread(
                target=self._process_ai_message_async,
                args=(self.env.cr.dbname, self.env.uid, self.id, message_body)
            )
            thread.daemon = True
            thread.start()
            _logger.info(f"Async thread started successfully")

        return message

    def _format_ai_message_body(self, content, graph_data=None):
        """Format AI message content as HTML for proper display in Discuss

        Args:
            content: Text content to format
            graph_data: Optional dict with graph image data (base64)
        """
        if not content and not graph_data:
            return ''

        # Use Odoo's plaintext2html to convert plain text to HTML
        # This preserves line breaks and formats the text properly
        html_content = plaintext2html(content) if content else ''

        # Embed graph if provided
        if graph_data and graph_data.get('image_base64'):
            # Add graph image inline
            graph_html = f'''<div style="margin: 15px 0;">
                <img src="data:image/png;base64,{graph_data['image_base64']}"
                     style="max-width: 100%; height: auto; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);"
                     alt="Generated Graph"/>
            </div>'''
            html_content = html_content + graph_html

        return html_content

    def _process_ai_message_async(self, dbname, uid, channel_id, message_body):
        """Process AI message asynchronously in a separate thread with new cursor"""
        _logger.info(f"[ASYNC] Starting async processing for channel {channel_id}")
        try:
            # Create a new registry and cursor for this thread
            import odoo
            registry = odoo.registry(dbname)
            _logger.info(f"[ASYNC] Registry obtained for {dbname}")

            with registry.cursor() as cr:
                _logger.info(f"[ASYNC] New cursor created")
                env = api.Environment(cr, uid, {})
                channel = env['mail.channel'].browse(channel_id)

                _logger.info(f"[ASYNC] About to process message: {message_body[:50] if message_body else 'NO BODY'}")

                # Process the AI message
                channel._process_ai_message(message_body)

                # Commit the transaction
                cr.commit()
                _logger.info(f"[ASYNC] Processing complete and committed")

        except Exception as e:
            _logger.exception(f"[ASYNC] Error in async AI message processing: {e}")
            # Try to post error message with a new cursor
            try:
                import odoo
                registry = odoo.registry(dbname)
                with registry.cursor() as cr:
                    env = api.Environment(cr, uid, {})
                    channel = env['mail.channel'].browse(channel_id)
                    ai_bot = env['res.partner'].sudo().search([
                        ('name', '=', 'AI Assistant Bot')
                    ], limit=1)

                    if ai_bot:
                        error_msg = f"Sorry, I encountered an error processing your message: {str(e)}"
                        posted_message = channel.message_post(
                            body=channel._format_ai_message_body(error_msg),
                            author_id=ai_bot.id,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment'
                        )

                        # Manually trigger bus notification to update UI
                        try:
                            env['bus.bus']._sendone(channel, 'mail.channel/new_message', {
                                'id': channel.id,
                                'message': posted_message.message_format()[0]
                            })
                        except Exception:
                            pass  # Bus notification is optional

                        cr.commit()
            except Exception as post_error:
                _logger.exception(f"[ASYNC] Failed to post error message: {post_error}")

    def _process_ai_message(self, user_message_body):
        """Process user message and generate AI response

        Args:
            user_message_body: String content of the user's message
        """
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
                'content': user_message_body,
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
                    # Process tool calls and get final response
                    self._process_tool_calls(
                        session,
                        tool_calls,
                        content,
                        openrouter_api_key,
                        openrouter_model,
                        system_prompt,
                        tools
                    )
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
                        # Format the message body for proper display in Discuss
                        formatted_body = self._format_ai_message_body(content)
                        posted_message = self.message_post(
                            body=formatted_body,
                            author_id=ai_bot.id,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment'
                        )

                        # Manually trigger bus notification to update UI
                        self.env['bus.bus']._sendone(self, 'mail.channel/new_message', {
                            'id': self.id,
                            'message': posted_message.message_format()[0]
                        })

        except Exception as e:
            _logger.error(f"Error processing AI message: {e}", exc_info=True)
            # Post error message to channel with AI bot as author to prevent recursion
            try:
                ai_bot = self.env['res.partner'].sudo().search([
                    ('name', '=', 'AI Assistant Bot')
                ], limit=1)

                if ai_bot:
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    formatted_error = self._format_ai_message_body(error_message)
                    posted_message = self.with_context(mail_create_nosubscribe=True).message_post(
                        body=formatted_error,
                        author_id=ai_bot.id,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment'
                    )

                    # Manually trigger bus notification to update UI
                    try:
                        self.env['bus.bus']._sendone(self, 'mail.channel/new_message', {
                            'id': self.id,
                            'message': posted_message.message_format()[0]
                        })
                    except Exception:
                        pass  # Bus notification is optional
            except Exception as post_error:
                # If even posting the error fails, just log it
                _logger.error(f"Failed to post error message to channel: {post_error}")

    def _build_context_aware_prompt(self):
        """Build context-aware system prompt"""
        config_params = self.env['ir.config_parameter'].sudo()

        # Get user context
        user = self.env.user

        # Create a clean, concise system prompt for Discuss interface
        # Don't use the verbose config system prompt as it confuses function calling
        prompt = f"""You are an expert Odoo ERP assistant integrated into the Discuss messaging interface.
You help users with data queries, record creation/updates, and workflow tasks.

USER CONTEXT:
- Name: {user.name}
- Language: {user.lang}
- Timezone: {user.tz}
- Company: {user.company_id.name if user.company_id else 'N/A'}

INSTRUCTIONS:
- Respond in the user's language ({user.lang})
- Use available tools to access and manipulate Odoo data
- Be concise and professional
- When using tools, wait for results before responding to the user
- Provide clear, actionable answers based on real data

Available tools allow you to:
- search_records: Query Odoo data (sales, customers, products, etc.)
- create_record: Create new records
- write_record: Update existing records
- generate_graph: Create visualizations when explicitly requested

Use tools when needed to provide accurate, data-driven responses."""

        return prompt

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

    def _process_tool_calls(self, session, tool_calls, assistant_content, openrouter_api_key, openrouter_model, system_prompt, tools):
        """Process tool calls from AI and get final response"""
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
        graph_data = None  # Track graph data if generated

        for tc in tool_calls:
            try:
                tool_name = tc['function']['name']
                tool_args = json.loads(tc['function']['arguments'])

                _logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                result = mcp_server.call_tool(tool_name, tool_args)

                # Extract graph data if this was a generate_graph call
                if tool_name == 'generate_graph' and result.get('success') and result.get('image_base64'):
                    graph_data = {'image_base64': result['image_base64']}
                    _logger.info(f"Graph generated successfully, image size: {len(result['image_base64'])} chars")

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
                error_result = {'success': False, 'error': str(e)}
                self.env['ai.chat.message'].create({
                    'session_id': session.id,
                    'role': 'tool',
                    'content': json.dumps(error_result),
                    'tool_call_id': tc['id'],
                    'metadata': json.dumps({'tool_name': tool_name, 'error': True}),
                })

        # After tools execute, call AI again with tool results to get final response
        _logger.info("Calling AI again with tool results to get final response")

        # Get updated messages including tool results
        messages = session.get_messages_for_api()
        messages.insert(0, {
            'role': 'system',
            'content': system_prompt
        })

        # Call AI again (without tools this time to force a final answer)
        try:
            final_response = self._call_openrouter_api(
                openrouter_api_key,
                openrouter_model,
                messages,
                tools=None  # Don't allow more tool calls, force final answer
            )

            if final_response and final_response.get('choices'):
                final_content = final_response['choices'][0]['message'].get('content', '')

                # Create final assistant message
                self.env['ai.chat.message'].create({
                    'session_id': session.id,
                    'role': 'assistant',
                    'content': final_content,
                })

                # Post final response to channel
                ai_bot = self.env['res.partner'].sudo().search([
                    ('name', '=', 'AI Assistant Bot')
                ], limit=1)

                if ai_bot and final_content:
                    # Format body with graph if available
                    formatted_body = self._format_ai_message_body(final_content, graph_data=graph_data)
                    posted_message = self.message_post(
                        body=formatted_body,
                        author_id=ai_bot.id,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment'
                    )

                    # Manually trigger bus notification to update UI
                    self.env['bus.bus']._sendone(self, 'mail.channel/new_message', {
                        'id': self.id,
                        'message': posted_message.message_format()[0]
                    })

        except Exception as e:
            _logger.error(f"Error getting final AI response after tool execution: {e}")
            # Post error message
            ai_bot = self.env['res.partner'].sudo().search([
                ('name', '=', 'AI Assistant Bot')
            ], limit=1)

            if ai_bot:
                error_message = f"I executed the tools but encountered an error getting the final response: {str(e)}"
                formatted_error = self._format_ai_message_body(error_message)
                posted_message = self.message_post(
                    body=formatted_error,
                    author_id=ai_bot.id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )

                # Manually trigger bus notification to update UI
                try:
                    self.env['bus.bus']._sendone(self, 'mail.channel/new_message', {
                        'id': self.id,
                        'message': posted_message.message_format()[0]
                    })
                except Exception:
                    pass  # Bus notification is optional
