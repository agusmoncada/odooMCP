"""Extension of mail.thread to enable AI responses in record chatter"""

import logging
import threading
import json

from odoo import models, api

_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    """Extend mail.thread to intercept @mentions of AI bot in record chatter"""
    _inherit = 'mail.thread'

    def message_post(self, **kwargs):
        """Override to detect AI mentions in record chatter and trigger AI response"""
        # Call parent first to create the message
        message = super().message_post(**kwargs)

        # Only process if we have a message with an author
        if not message or not message.author_id:
            return message

        # Get AI bot partner
        ai_bot = self.env['res.partner'].sudo().search([
            ('email', '=', 'ai.assistant@odoo.local')
        ], limit=1)

        if not ai_bot:
            return message

        # Don't process messages FROM the AI bot (prevent recursion)
        if message.author_id.id == ai_bot.id:
            return message

        # Check if AI bot is mentioned in this message
        ai_is_mentioned = ai_bot.id in message.partner_ids.ids

        if not ai_is_mentioned:
            return message

        # AI was mentioned in this record's chatter
        # Process the message asynchronously
        _logger.info(f"AI mentioned in {self._name} record {self.id}, message: {message.id}")

        # Get message content
        message_body = message.body or ''

        # Process AI response asynchronously
        thread = threading.Thread(
            target=self._process_ai_chatter_message_async,
            args=(self.env.cr.dbname, self.env.uid, self._name, self.id, message_body, message.id)
        )
        thread.daemon = True
        thread.start()

        return message

    def _process_ai_chatter_message_async(self, dbname, uid, model_name, record_id, message_body, original_message_id):
        """Process AI chatter message in background thread with new cursor"""
        import odoo
        from odoo import api

        try:
            registry = odoo.registry(dbname)
            with registry.cursor() as cr:
                env = api.Environment(cr, uid, {})

                # Get the record
                record = env[model_name].browse(record_id)
                if not record.exists():
                    _logger.error(f"Record {model_name}({record_id}) not found")
                    return

                # Get AI bot
                ai_bot = env['res.partner'].sudo().search([
                    ('email', '=', 'ai.assistant@odoo.local')
                ], limit=1)

                if not ai_bot:
                    _logger.error("AI bot not found")
                    return

                # Post thinking message
                thinking_message = None
                try:
                    thinking_body = "🤔 AI is thinking..."
                    thinking_message = record.with_context(
                        mail_create_nosubscribe=True,
                        mail_channel_noautofollow=True
                    ).message_post(
                        body=thinking_body,
                        author_id=ai_bot.id,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment'
                        # Don't use parent_id here - original message may not be committed yet
                    )
                    env.cr.commit()
                    _logger.info(f"Posted thinking message to {model_name}({record_id})")
                except Exception as e:
                    _logger.warning(f"Could not post thinking message: {e}")

                # Get AI configuration
                config_params = env['ir.config_parameter'].sudo()
                openrouter_api_key = config_params.get_param('odoo_ai_chat.openrouter_api_key')
                openrouter_model = config_params.get_param('odoo_ai_chat.openrouter_model', 'openai/gpt-3.5-turbo')

                if not openrouter_api_key:
                    _logger.error("OpenRouter API key not configured")
                    return

                # Build context-aware prompt for this record
                system_prompt = self._build_chatter_prompt(env, record, model_name)

                # Prepare messages for AI
                messages = [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': message_body}
                ]

                # Get MCP tools
                tools = None
                mcp_enabled = config_params.get_param('odoo_ai_chat.mcp_tools_enabled', 'True') == 'True'
                if mcp_enabled:
                    try:
                        mcp_server = env['mcp.server.registry'].sudo()
                        mcp_tools = mcp_server.list_tools()

                        # Convert MCP tools to OpenRouter format
                        tools = []
                        for tool in mcp_tools:
                            tools.append({
                                'type': 'function',
                                'function': {
                                    'name': tool['name'],
                                    'description': tool['description'],
                                    'parameters': tool.get('inputSchema', {})
                                }
                            })
                    except Exception as e:
                        _logger.error(f"Error loading MCP tools: {e}")

                # Call AI
                ai_response = env['mail.channel']._call_openrouter_api(
                    openrouter_api_key,
                    openrouter_model,
                    messages,
                    tools=tools
                )

                if not ai_response or not ai_response.get('choices'):
                    _logger.error("No response from AI")
                    return

                response_message = ai_response['choices'][0]['message']
                response_content = response_message.get('content', '')
                tool_calls = response_message.get('tool_calls')

                iteration = 0  # Track iterations for logging

                # If AI wants to use tools, process them
                if tool_calls:
                    _logger.info(f"AI wants to call {len(tool_calls)} tools on {model_name}({record_id})")

                    # Execute tool calls
                    mcp_server = env['mcp.server.registry'].sudo()
                    max_iterations = 20  # Increased from 10 to handle complex multi-step tasks

                    while tool_calls and iteration < max_iterations:
                        iteration += 1
                        _logger.info(f"Tool iteration {iteration}: processing {len(tool_calls)} calls")

                        # Add assistant message with tool calls to history
                        messages.append({
                            'role': 'assistant',
                            'content': response_content or '',
                            'tool_calls': tool_calls
                        })

                        # Execute each tool
                        for tc in tool_calls:
                            tool_name = tc['function']['name']
                            tool_args = tc['function'].get('arguments', {})
                            if isinstance(tool_args, str):
                                tool_args = json.loads(tool_args)

                            tool_call_id = tc['id']

                            _logger.info(f"Executing {tool_name} with args: {tool_args}")

                            # Use savepoint to isolate tool execution
                            # If tool fails, we can rollback and continue with other tools
                            try:
                                env.cr.execute(f'SAVEPOINT tool_exec_{iteration}_{tool_call_id[:8]}')
                                result = mcp_server.call_tool(tool_name, tool_args)
                                env.cr.execute(f'RELEASE SAVEPOINT tool_exec_{iteration}_{tool_call_id[:8]}')
                                _logger.info(f"Tool {tool_name} completed successfully")
                            except Exception as e:
                                _logger.error(f"Tool {tool_name} failed: {e}")
                                # Rollback to savepoint to recover transaction
                                try:
                                    env.cr.execute(f'ROLLBACK TO SAVEPOINT tool_exec_{iteration}_{tool_call_id[:8]}')
                                    env.cr.execute(f'RELEASE SAVEPOINT tool_exec_{iteration}_{tool_call_id[:8]}')
                                except Exception as rollback_error:
                                    _logger.error(f"Could not rollback savepoint: {rollback_error}")
                                # Return error in result so AI sees what went wrong
                                result = {'success': False, 'error': str(e)}

                            # Add tool result to messages
                            messages.append({
                                'role': 'tool',
                                'tool_call_id': tool_call_id,
                                'name': tool_name,
                                'content': json.dumps(result)
                            })

                        # Call AI again with tool results
                        next_response = env['mail.channel']._call_openrouter_api(
                            openrouter_api_key,
                            openrouter_model,
                            messages,
                            tools=tools
                        )

                        if next_response and next_response.get('choices'):
                            next_message = next_response['choices'][0]['message']
                            response_content = next_message.get('content', '')
                            tool_calls = next_message.get('tool_calls')

                            if not tool_calls:
                                # No more tools, we're done
                                break
                        else:
                            break

                    # Check if we hit max iterations
                    if iteration >= max_iterations:
                        _logger.warning(f"Reached max iterations ({max_iterations}) on {model_name}({record_id})")
                        if not response_content:
                            response_content = f"I completed {iteration} operations but reached the maximum number of steps allowed. Some tasks may be incomplete. Please let me know if you'd like me to continue."

                # Delete thinking message
                if thinking_message:
                    try:
                        thinking_message.unlink()
                    except Exception as e:
                        _logger.warning(f"Could not delete thinking message: {e}")

                # Post AI response
                if response_content:
                    record.with_context(
                        mail_create_nosubscribe=True,
                        mail_channel_noautofollow=True
                    ).message_post(
                        body=response_content,
                        author_id=ai_bot.id,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                        parent_id=original_message_id  # Reply to the @mention
                    )
                    env.cr.commit()
                    _logger.info(f"Posted AI response to {model_name}({record_id}) after {iteration} iterations")

        except Exception as e:
            _logger.error(f"Error processing AI chatter message: {e}", exc_info=True)

    @api.model
    def _build_chatter_prompt(self, env, record, model_name):
        """Build system prompt for chatter context"""
        user = env.user

        # Get record info
        record_name = record.display_name if hasattr(record, 'display_name') else str(record.id)
        record_info = f"- Record: {model_name} ({record_name}, ID: {record.id})"

        # Try to get some key fields
        key_fields_info = ""
        if hasattr(record, 'partner_id') and record.partner_id:
            key_fields_info += f"\n- Customer: {record.partner_id.name}"
        if hasattr(record, 'amount_total'):
            key_fields_info += f"\n- Amount: {record.amount_total}"
        if hasattr(record, 'state'):
            key_fields_info += f"\n- Status: {record.state}"

        prompt = f"""You are an AI assistant helping with an Odoo ERP record.

CONTEXT:
- User: {user.name} ({user.lang})
- Company: {user.company_id.name if user.company_id else 'N/A'}

CURRENT RECORD:
{record_info}{key_fields_info}

INSTRUCTIONS:
- You've been @mentioned in this record's chatter
- The user's message is requesting help with THIS specific record
- You have access to tools to read, create, and update Odoo records
- When the user asks you to update THIS record, use the write_record tool with model='{model_name}' and record_id={record.id}
- Be concise and action-oriented
- Confirm what you've done clearly
- If you encounter errors (missing required fields, etc.), explain clearly what happened and suggest alternatives

CREATING REMINDERS/ACTIVITIES:
- To create reminders, use project.task model (simpler, fewer required fields)
- DO NOT use mail.activity directly - it requires activity_type_id which is complex to set up
- Example: create_record(model='project.task', values={{'name': 'Call client', 'date_deadline': '2025-11-23', 'user_id': {user.id}}})

EXAMPLE 1 - Update Status:
User: "@ai mark this as confirmed"
You should:
1. Call write_record(model='{model_name}', record_id={record.id}, values={{'state': 'sale'}})
2. Respond: "✅ I've confirmed this quotation. It's now a sales order."

EXAMPLE 2 - Create Reminder:
User: "@ai remind me to call this client tomorrow"
You should:
1. Call create_record(model='project.task', values={{'name': 'Call {record_name}', 'date_deadline': 'tomorrow', 'user_id': {user.id}}})
2. Respond: "✅ I've created a task to remind you to call this client tomorrow."

Available tools:
- search_records: Query Odoo data
- create_record: Create new records (use project.task for reminders)
- write_record: Update records (use this to update THIS record)
- generate_graph: Create visualizations

Respond in {user.lang}."""

        return prompt
