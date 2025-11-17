"""Main Controller for AI Chat"""

import json
import logging
import base64
from datetime import datetime, date

from odoo import http
from odoo.http import request

from ..models.ai_provider import OpenRouterProvider

_logger = logging.getLogger(__name__)


class OdooJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles Odoo-specific types"""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, bytes):
            return base64.b64encode(obj).decode('utf-8')
        return super().default(obj)


class AIChatController(http.Controller):
    """Controller for AI Chat endpoints"""

    @http.route('/ai_chat/send_message', type='json', auth='user')
    def send_message(self, session_id=None, message=None, view_context=None, user_context=None, **kwargs):
        """
        Send a message to the AI and get a response

        Args:
            session_id: ID of the chat session (creates new if None)
            message: User message text
            view_context: Current view/module/action context (optional)
            user_context: User language, timezone, etc. (optional)

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
                _logger.error("OpenRouter API key not configured")
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

            # Add context-aware system prompt
            system_prompt = self._build_context_aware_prompt(
                config['system_prompt'],
                view_context=view_context,
                user_context=user_context
            )
            if system_prompt:
                messages.append({
                    'role': 'system',
                    'content': system_prompt
                })

            # Add conversation history
            messages.extend(session.get_messages_for_api())

            # Get MCP tools if enabled
            tools = []
            tools_were_executed = False  # Track if we executed tools
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
                    # Save tool_calls for later display
                    tool_calls_for_display = response.get('tool_calls', [])

                    # Save assistant message with tool_calls BEFORE executing tools
                    # This ensures correct message ordering in the database
                    assistant_with_tools_msg = Message.create({
                        'session_id': session.id,
                        'role': 'assistant',
                        'content': response.get('message') or '',
                        'tool_calls': json.dumps(tool_calls_for_display)
                    })

                    response = self._execute_tool_calls(
                        session=session,
                        response=response,
                        ai_provider=ai_provider,
                        config=config
                    )

                    # Add tool_calls back for frontend display
                    response['tool_calls'] = tool_calls_for_display
                    tools_were_executed = True
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
                # If tools were executed, we need to save the final response
                # If no tools, just save the regular response
                message_vals = {
                    'session_id': session.id,
                    'role': 'assistant',
                    'content': response.get('message', ''),
                }

                # Don't save tool_calls on the final message (already saved earlier)
                if not tools_were_executed and response.get('tool_calls'):
                    message_vals['tool_calls'] = json.dumps(response.get('tool_calls', []))

                # Store graph data in metadata if present
                if response.get('graph_data'):
                    message_vals['metadata'] = json.dumps({'graph_data': response.get('graph_data')})

                assistant_message = Message.create(message_vals)

                return {
                    'success': True,
                    'session_id': session.id,
                    'message': response.get('message', ''),
                    'message_id': assistant_message.id,
                    'tool_calls': response.get('tool_calls', []),
                    'graph_data': response.get('graph_data')
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
        """Execute MCP tool calls and get final AI response, looping if more tools are needed"""
        current_messages = response.get('messages', [])
        Message = http.request.env['ai.chat.message']
        mcp_registry = http.request.env['mcp.server.registry']
        tools = mcp_registry.list_tools()

        graph_data = None
        max_iterations = 20  # Prevent infinite loops (allows batching up to 20 operations)
        iteration = 0

        # Loop to handle multiple rounds of tool calls
        while iteration < max_iterations:
            tool_calls = response.get('tool_calls', [])

            if not tool_calls:
                # No more tool calls, we're done
                break

            iteration += 1
            _logger.info(f"Tool execution iteration {iteration}: processing {len(tool_calls)} tool calls")

            # Execute each tool call and save results immediately
            for tool_call in tool_calls:
                try:
                    tool_name = tool_call['name']
                    tool_args = tool_call['arguments']
                    tool_call_id = tool_call['tool_call_id']

                    _logger.info(f"Executing tool: {tool_name} with args: {tool_args}")

                    # Execute tool via MCP
                    tool_result = mcp_registry.call_tool(tool_name, tool_args)

                    # Log errors from tool execution
                    if not tool_result.get('success'):
                        _logger.error(f"Tool {tool_name} failed: {tool_result.get('error', 'Unknown error')}")

                    # Extract graph data if this was a generate_graph call
                    if tool_name == 'generate_graph' and tool_result.get('success'):
                        graph_data = tool_result.get('graph_data')

                    # Add tool result to messages
                    current_messages.append({
                        'role': 'tool',
                        'tool_call_id': tool_call_id,
                        'name': tool_name,
                        'content': json.dumps(tool_result, cls=OdooJSONEncoder)
                    })

                    # Save tool result message IMMEDIATELY
                    metadata = {'tool_name': tool_name}
                    if graph_data:
                        metadata['graph_data'] = graph_data

                    Message.create({
                        'session_id': session.id,
                        'role': 'tool',
                        'content': json.dumps(tool_result, cls=OdooJSONEncoder),
                        'tool_call_id': tool_call_id,
                        'metadata': json.dumps(metadata)
                    })

                    # Commit after each tool result
                    http.request.env.cr.commit()

                except Exception as e:
                    _logger.exception(f"Error executing tool {tool_name}")
                    # Save error as tool result to maintain message integrity
                    error_result = {'success': False, 'error': str(e)}
                    current_messages.append({
                        'role': 'tool',
                        'tool_call_id': tool_call_id,
                        'name': tool_name,
                        'content': json.dumps(error_result)
                    })
                    Message.create({
                        'session_id': session.id,
                        'role': 'tool',
                        'content': json.dumps(error_result),
                        'tool_call_id': tool_call_id,
                        'metadata': json.dumps({'tool_name': tool_name, 'error': True})
                    })
                    http.request.env.cr.commit()

            # After executing tools, ask AI if it wants to call more tools or provide final response
            try:
                _logger.info(f"Calling AI after tool execution to check for more tool calls")

                # Check if we're at max iterations before calling AI again
                if iteration >= max_iterations:
                    _logger.warning(f"Reached maximum tool execution iterations ({max_iterations})")
                    # Ask for final summary without allowing more tool calls
                    final_response = ai_provider.chat(
                        messages=current_messages,
                        temperature=config['temperature'],
                        max_tokens=config['max_tokens']
                    )
                    choice = final_response.get('choices', [{}])[0]
                    final_message = choice.get('message', {}).get('content', '')
                    return {
                        'success': True,
                        'message': final_message or "I've completed the available tool operations.",
                        'graph_data': graph_data
                    }

                # Call chat_with_tools again - this allows the AI to see tool results
                # and decide whether to call more tools or provide a final response
                response = ai_provider.chat_with_tools(
                    messages=current_messages,
                    mcp_tools=tools
                )

                # If the AI wants to execute more tools, loop will continue
                if response.get('requires_tool_execution'):
                    # Don't save intermediate assistant messages - they clutter the UI
                    # Just update current_messages for the next iteration
                    current_messages = response.get('messages', current_messages)
                    continue  # Loop back to execute more tools

                # No more tool calls - AI provided final response
                _logger.info(f"AI provided final response after {iteration} tool execution rounds")
                return {
                    'success': True,
                    'message': response.get('message', ''),
                    'graph_data': graph_data
                }

            except Exception as e:
                _logger.exception("Error in tool execution loop")
                return {
                    'success': True,  # Tool results are saved
                    'message': f"I encountered an error while processing: {str(e)}",
                    'graph_data': graph_data
                }

        # This should never be reached due to the iteration check above
        _logger.warning(f"Exited tool execution loop unexpectedly")
        return {
            'success': True,
            'message': "Tool execution completed.",
            'graph_data': graph_data
        }

    def _build_context_aware_prompt(self, base_prompt, view_context=None, user_context=None):
        """Build context-aware system prompt with user and view context"""
        context_parts = [base_prompt] if base_prompt else []

        # Add user context
        user = request.env.user
        context_parts.append(f"""
USER CONTEXT:
- Name: {user.name}
- Language: {user.lang}
- Timezone: {user.tz or 'UTC'}
- Company: {user.company_id.name if user.company_id else 'N/A'}
- Email: {user.email or 'N/A'}

IMPORTANT LANGUAGE INSTRUCTION:
You MUST respond in the user's configured language ({user.lang}).
- If the language is Spanish (es_ES, es_MX, es_AR, etc.), respond in Spanish.
- If the language is French (fr_FR, fr_CA, etc.), respond in French.
- If the language is English (en_US, en_GB, etc.), respond in English.
- And so on for other languages.
Only use a different language if the user explicitly requests it.
""")

        # Add view context if provided
        if view_context:
            current_model = view_context.get('model')
            action_name = view_context.get('action_name')
            active_id = view_context.get('active_id')
            view_type = view_context.get('view_type')

            if current_model or action_name:
                context_section = "\nCURRENT VIEW CONTEXT:"

                if action_name:
                    context_section += f"\n- User is currently in: {action_name}"

                if current_model:
                    context_section += f"\n- Working with model: {current_model}"

                if view_type:
                    context_section += f"\n- View type: {view_type}"

                if active_id and current_model:
                    # Try to get record name for better context
                    try:
                        record = request.env[current_model].browse(active_id)
                        if record.exists():
                            record_name = record.display_name or record.name if hasattr(record, 'name') else str(active_id)
                            context_section += f"\n- Looking at record: {record_name} (ID: {active_id})"
                    except Exception as e:
                        _logger.debug(f"Could not fetch record context: {e}")
                        context_section += f"\n- Active record ID: {active_id}"

                context_section += "\n\nThe user is likely asking about something related to this view or record. Consider this context when providing assistance."
                context_parts.append(context_section)

        # Add user permissions context (optional, lightweight)
        try:
            permissions = []
            if user.has_group('base.group_system'):
                permissions.append('System Administrator')
            if user.has_group('sales_team.group_sale_manager'):
                permissions.append('Sales Manager')
            if user.has_group('account.group_account_manager'):
                permissions.append('Accounting Manager')

            if permissions:
                context_parts.append(f"\nUSER PERMISSIONS: {', '.join(permissions)}")
        except Exception as e:
            _logger.debug(f"Could not fetch user permissions: {e}")

        return "\n".join(context_parts)

    @http.route('/ai_chat/get_user_context', type='json', auth='user')
    def get_user_context(self, **kwargs):
        """Get comprehensive user context for AI"""
        try:
            user = request.env.user

            # Basic user info
            user_context_data = {
                'id': user.id,
                'name': user.name,
                'login': user.login,
                'email': user.email,
                'lang': user.lang,
                'tz': user.tz or 'UTC',
            }

            # Company info
            if user.company_id:
                user_context_data['company'] = {
                    'id': user.company_id.id,
                    'name': user.company_id.name,
                }

            # Check specific permissions
            user_context_data['permissions'] = {
                'is_admin': user.has_group('base.group_system'),
                'is_sales_user': user.has_group('sales_team.group_sale_salesman') if request.env['ir.model'].search([('model', '=', 'sales_team')]) else False,
                'is_sales_manager': user.has_group('sales_team.group_sale_manager') if request.env['ir.model'].search([('model', '=', 'sales_team')]) else False,
                'is_accounting_user': user.has_group('account.group_account_user') if request.env['ir.model'].search([('model', '=', 'account')]) else False,
            }

            return {
                'success': True,
                'user_context': user_context_data
            }

        except Exception as e:
            _logger.exception("Error getting user context")
            return {'success': False, 'error': str(e)}

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

            messages = []
            for m in session.chat_message_ids.sorted('create_date'):
                # Skip tool result messages - they're technical implementation details
                if m.role == 'tool':
                    continue

                # Also skip assistant messages with tool_calls but no content
                # (these are intermediate coordination messages)
                if m.role == 'assistant' and m.tool_calls and not m.content:
                    continue

                msg_data = {
                    'id': m.id,
                    'role': m.role,
                    'content': m.content,
                    'create_date': m.create_date.isoformat(),
                    'tool_calls': m.tool_calls
                }

                # Extract graph_data from metadata if present
                if m.metadata:
                    try:
                        metadata = json.loads(m.metadata)
                        if metadata.get('graph_data'):
                            msg_data['graph_data'] = metadata['graph_data']
                    except json.JSONDecodeError:
                        pass

                messages.append(msg_data)

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

    @http.route('/ai_chat/upload_pdf', type='http', auth='user', methods=['POST'], csrf=False)
    def upload_pdf(self, **kwargs):
        """Handle PDF file upload and processing"""
        try:
            file = request.httprequest.files.get('file')
            session_id = request.params.get('session_id')

            if not file:
                return request.make_json_response({
                    'success': False,
                    'error': 'No file provided'
                })

            # Read file content
            pdf_content = file.read()
            filename = file.filename

            # Validate file type
            if not filename.lower().endswith('.pdf'):
                return request.make_json_response({
                    'success': False,
                    'error': 'Only PDF files are supported'
                })

            # Validate file size (max 10MB)
            max_size = 10 * 1024 * 1024  # 10MB
            if len(pdf_content) > max_size:
                return request.make_json_response({
                    'success': False,
                    'error': 'File size exceeds 10MB limit'
                })

            # Process PDF
            from ..models.pdf_processor import PDFInvoiceProcessor
            processor = PDFInvoiceProcessor(request.env)
            result = processor.process_pdf(pdf_content, filename)

            if result['success']:
                # Store PDF as attachment for later use
                Attachment = request.env['ir.attachment']
                pdf_b64 = base64.b64encode(pdf_content).decode('utf-8')

                attachment = Attachment.create({
                    'name': filename,
                    'datas': pdf_b64,
                    'res_model': 'ai.chat.session',
                    'res_id': int(session_id) if session_id else False,
                    'mimetype': 'application/pdf',
                    'description': 'Uploaded invoice PDF for processing'
                })

                return request.make_json_response({
                    'success': True,
                    'attachment_id': attachment.id,
                    'filename': filename,
                    'invoice_data': result['data'],
                    'raw_text_preview': result.get('raw_text', '')[:200]
                })
            else:
                return request.make_json_response(result)

        except Exception as e:
            _logger.exception("Error uploading PDF")
            return request.make_json_response({
                'success': False,
                'error': str(e)
            })

    @http.route('/ai_chat/process_invoice', type='json', auth='user')
    def process_invoice(self, attachment_id=None, **kwargs):
        """Process uploaded PDF and create vendor bill"""
        try:
            if not attachment_id:
                return {'success': False, 'error': 'Attachment ID is required'}

            # Get attachment
            Attachment = request.env['ir.attachment']
            attachment = Attachment.browse(attachment_id)

            if not attachment.exists():
                return {'success': False, 'error': 'Attachment not found'}

            # Decode PDF content
            pdf_content = base64.b64decode(attachment.datas)

            # Process PDF
            from ..models.pdf_processor import PDFInvoiceProcessor
            processor = PDFInvoiceProcessor(request.env)

            result = processor.process_pdf(pdf_content, attachment.name)

            if not result['success']:
                return result

            # Create vendor bill
            invoice_result = processor.create_vendor_bill(
                invoice_data=result['data'],
                pdf_content_b64=attachment.datas,
                filename=attachment.name
            )

            if invoice_result['success']:
                # Delete temporary attachment
                attachment.unlink()

            return invoice_result

        except Exception as e:
            _logger.exception("Error processing invoice")
            return {'success': False, 'error': str(e)}

    @http.route('/ai_chat/open_discuss_channel', type='http', auth='user')
    def open_discuss_channel(self, **kwargs):
        """Open or create AI Assistant channel in Discuss"""
        try:
            # Get or create AI channel
            session_model = request.env['ai.chat.session']
            channel = session_model.get_or_create_ai_channel_for_user()

            # Redirect to Discuss with a message
            return request.redirect('/web#action=mail.action_discuss&active_id=%s' % channel.id)

        except Exception as e:
            _logger.exception("Error opening AI discuss channel")
            return request.redirect('/web')

    @http.route('/ai_chat/update_channel_context', type='json', auth='user')
    def update_channel_context(self, context=None, **kwargs):
        """Update the AI channel's current view context

        This endpoint is called by the frontend when the user navigates to a new page/record.
        It stores the context so the AI knows what the user is currently viewing.

        Args:
            context: Dict with view context (model, active_id, etc.)

        Returns:
            Dict with success status
        """
        try:
            # Get or create AI channel for this user
            session_model = request.env['ai.chat.session']
            channel = session_model.get_or_create_ai_channel_for_user()

            # Update the channel's view context
            if context:
                channel.update_view_context(context)

            return {'success': True}

        except Exception as e:
            _logger.exception("Error updating channel context")
            return {'success': False, 'error': str(e)}
