"""Main Controller for AI Chat"""

import json
import logging

from odoo import http
from odoo.http import request

from ..models.ai_provider import OpenRouterProvider

_logger = logging.getLogger(__name__)


class AIChatController(http.Controller):
    """Controller for AI Chat endpoints"""

    @http.route('/ai_chat/send_message', type='json', auth='user')
    def send_message(self, session_id=None, message=None, **kwargs):
        """
        Send a message to the AI and get a response

        Args:
            session_id: ID of the chat session (creates new if None)
            message: User message text

        Returns:
            Dict with response data
        """
        try:
            if not message:
                return {'error': 'Message is required'}

            # Get or create session
            Session = request.env['ai.chat.session']
            if session_id:
                session = Session.browse(session_id)
                if not session.exists() or session.user_id != request.env.user:
                    return {'error': 'Invalid session'}
            else:
                # Create new session
                session = Session.create({
                    'name': message[:50] if len(message) > 50 else message,
                    'user_id': request.env.user.id
                })

            # Create user message
            Message = request.env['ai.chat.message']
            user_message = Message.create({
                'session_id': session.id,
                'role': 'user',
                'content': message
            })

            # Get AI configuration
            config = request.env['res.config.settings'].get_ai_config()

            if not config['api_key']:
                return {
                    'error': 'OpenRouter API key not configured. Please configure it in Settings > AI Chat.'
                }

            # Initialize AI provider
            ai_provider = OpenRouterProvider(
                api_key=config['api_key'],
                model=config['model'],
                site_url=config['site_url'],
                site_name=config['site_name']
            )

            # Prepare messages for AI
            messages = []

            # Add system prompt
            if config['system_prompt']:
                messages.append({
                    'role': 'system',
                    'content': config['system_prompt']
                })

            # Add conversation history
            messages.extend(session.get_messages_for_api())

            # Get MCP tools if enabled
            tools = []
            if config['mcp_tools_enabled']:
                mcp_registry = request.env['mcp.server.registry']
                tools = mcp_registry.list_tools()

            # Call AI with or without tools
            if tools:
                response = ai_provider.chat_with_tools(
                    messages=messages,
                    mcp_tools=tools
                )

                # Process tool calls if needed
                if response.get('requires_tool_execution'):
                    response = self._execute_tool_calls(
                        session=session,
                        response=response,
                        ai_provider=ai_provider,
                        config=config
                    )
            else:
                api_response = ai_provider.chat(
                    messages=messages,
                    temperature=config['temperature'],
                    max_tokens=config['max_tokens']
                )

                choice = api_response.get('choices', [{}])[0]
                ai_message_content = choice.get('message', {}).get('content', '')

                response = {
                    'success': True,
                    'message': ai_message_content
                }

            # Create assistant message
            if response.get('success'):
                assistant_message = Message.create({
                    'session_id': session.id,
                    'role': 'assistant',
                    'content': response.get('message', ''),
                    'tool_calls': json.dumps(response.get('tool_calls', [])) if response.get('tool_calls') else False
                })

                return {
                    'success': True,
                    'session_id': session.id,
                    'message': response.get('message', ''),
                    'message_id': assistant_message.id,
                    'tool_calls': response.get('tool_calls', [])
                }
            else:
                return {
                    'success': False,
                    'error': response.get('error', 'Unknown error')
                }

        except Exception as e:
            _logger.exception("Error in send_message")
            return {
                'success': False,
                'error': str(e)
            }

    def _execute_tool_calls(self, session, response, ai_provider, config):
        """Execute MCP tool calls and get final AI response"""
        try:
            tool_calls = response.get('tool_calls', [])
            current_messages = response.get('messages', [])

            Message = http.request.env['ai.chat.message']
            mcp_registry = http.request.env['mcp.server.registry']

            # Execute each tool call
            for tool_call in tool_calls:
                tool_name = tool_call['name']
                tool_args = tool_call['arguments']
                tool_call_id = tool_call['tool_call_id']

                _logger.info(f"Executing tool: {tool_name} with args: {tool_args}")

                # Execute tool via MCP
                tool_result = mcp_registry.call_tool(tool_name, tool_args)

                # Add tool result to messages
                current_messages.append({
                    'role': 'tool',
                    'tool_call_id': tool_call_id,
                    'name': tool_name,
                    'content': json.dumps(tool_result)
                })

                # Save tool result message
                Message.create({
                    'session_id': session.id,
                    'role': 'tool',
                    'content': json.dumps(tool_result),
                    'tool_call_id': tool_call_id
                })

            # Get final response from AI after tool execution
            final_response = ai_provider.chat(
                messages=current_messages,
                temperature=config['temperature'],
                max_tokens=config['max_tokens']
            )

            choice = final_response.get('choices', [{}])[0]
            final_message = choice.get('message', {}).get('content', '')

            return {
                'success': True,
                'message': final_message,
                'tool_calls': tool_calls
            }

        except Exception as e:
            _logger.exception("Error executing tool calls")
            return {
                'success': False,
                'error': f'Tool execution error: {str(e)}'
            }

    @http.route('/ai_chat/get_sessions', type='json', auth='user')
    def get_sessions(self, limit=20, **kwargs):
        """Get user's chat sessions"""
        try:
            Session = request.env['ai.chat.session']
            sessions = Session.search(
                [('user_id', '=', request.env.user.id)],
                limit=limit,
                order='create_date desc'
            )

            return {
                'success': True,
                'sessions': [{
                    'id': s.id,
                    'name': s.name,
                    'message_count': s.message_count,
                    'last_message_date': s.last_message_date.isoformat() if s.last_message_date else None,
                    'create_date': s.create_date.isoformat()
                } for s in sessions]
            }
        except Exception as e:
            _logger.exception("Error in get_sessions")
            return {'success': False, 'error': str(e)}

    @http.route('/ai_chat/get_messages', type='json', auth='user')
    def get_messages(self, session_id=None, **kwargs):
        """Get messages for a chat session"""
        try:
            if not session_id:
                return {'error': 'Session ID is required'}

            Session = request.env['ai.chat.session']
            session = Session.browse(session_id)

            if not session.exists() or session.user_id != request.env.user:
                return {'error': 'Invalid session'}

            messages = [{
                'id': m.id,
                'role': m.role,
                'content': m.content,
                'create_date': m.create_date.isoformat(),
                'tool_calls': m.tool_calls
            } for m in session.message_ids.sorted('create_date')]

            return {
                'success': True,
                'session_id': session.id,
                'session_name': session.name,
                'messages': messages
            }
        except Exception as e:
            _logger.exception("Error in get_messages")
            return {'success': False, 'error': str(e)}

    @http.route('/ai_chat/delete_session', type='json', auth='user')
    def delete_session(self, session_id=None, **kwargs):
        """Delete a chat session"""
        try:
            if not session_id:
                return {'error': 'Session ID is required'}

            Session = request.env['ai.chat.session']
            session = Session.browse(session_id)

            if not session.exists() or session.user_id != request.env.user:
                return {'error': 'Invalid session'}

            session.unlink()

            return {'success': True}
        except Exception as e:
            _logger.exception("Error in delete_session")
            return {'success': False, 'error': str(e)}

    @http.route('/ai_chat/new_session', type='json', auth='user')
    def new_session(self, name='New Chat', **kwargs):
        """Create a new chat session"""
        try:
            Session = request.env['ai.chat.session']
            session = Session.create({
                'name': name,
                'user_id': request.env.user.id
            })

            return {
                'success': True,
                'session_id': session.id,
                'session_name': session.name
            }
        except Exception as e:
            _logger.exception("Error in new_session")
            return {'success': False, 'error': str(e)}
