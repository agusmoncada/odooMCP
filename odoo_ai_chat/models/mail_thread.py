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
        # Pass the author_id directly so we don't need to read the message in the async thread
        mentioning_user_id = message.author_id.id if message.author_id else None
        thread = threading.Thread(
            target=self._process_ai_chatter_message_async,
            args=(self.env.cr.dbname, self.env.uid, self._name, self.id, message_body, mentioning_user_id)
        )
        thread.daemon = True
        thread.start()

        return message

    def _process_ai_chatter_message_async(self, dbname, uid, model_name, record_id, message_body, mentioning_user_id):
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

                # Get the user who mentioned us (passed directly to avoid transaction issues)
                mentioning_user_partner = None
                if mentioning_user_id:
                    mentioning_user_partner = env['res.partner'].browse(mentioning_user_id)
                    if not mentioning_user_partner.exists():
                        mentioning_user_partner = None

                # Get AI configuration
                config_params = env['ir.config_parameter'].sudo()
                openrouter_api_key = config_params.get_param('odoo_ai_chat.openrouter_api_key')
                openrouter_model = config_params.get_param('odoo_ai_chat.openrouter_model', 'openai/gpt-3.5-turbo')

                if not openrouter_api_key:
                    _logger.error("OpenRouter API key not configured")
                    return

                # Build context-aware prompt for this record
                system_prompt = self._build_chatter_prompt(env, record, model_name, mentioning_user_partner)

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

                # Post AI response with @ mention
                if response_content:
                    # Add @ mention if we know who mentioned us
                    partner_ids = []
                    if mentioning_user_partner:
                        partner_ids = [mentioning_user_partner.id]
                        # Format response with @ mention using Odoo's chatter mention format
                        mention_html = f'<a href="#" class="o_mail_redirect" data-oe-id="{mentioning_user_partner.id}" data-oe-model="res.partner">@{mentioning_user_partner.name}</a> '
                        response_content = mention_html + response_content

                    record.with_context(
                        mail_create_nosubscribe=True,
                        mail_channel_noautofollow=True
                    ).message_post(
                        body=response_content,
                        author_id=ai_bot.id,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                        # Don't use parent_id - causes FK constraint error with async cursor
                        partner_ids=partner_ids  # Notify the user who mentioned us
                    )
                    env.cr.commit()
                    _logger.info(f"Posted AI response to {model_name}({record_id}) after {iteration} iterations")

        except Exception as e:
            _logger.error(f"Error processing AI chatter message: {e}", exc_info=True)

    @api.model
    def _build_chatter_prompt(self, env, record, model_name, mentioning_user=None):
        """Build system prompt for chatter context"""
        user = env.user

        # Use mentioning_user if provided, otherwise fall back to current user
        target_user = mentioning_user if mentioning_user else user
        user_mention = f"@{target_user.name}"

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
- User who mentioned you: {target_user.name} ({target_user.lang})
- Company: {user.company_id.name if user.company_id else 'N/A'}

CURRENT RECORD:
{record_info}{key_fields_info}

CRITICAL RESPONSE GUIDELINES:
- ALWAYS start your response by mentioning the user: {user_mention}
- Be DIRECT and ACTION-ORIENTED - do NOT include internal thinking or narration
- DO NOT say things like "Ah I see...", "Let me update the user...", "I'll now...", etc.
- Just state what you did or what you found
- Use clear, concise language
- Confirm actions with emojis (✅ for success, ⚠️ for warnings, ❌ for errors)

CREATING REMINDERS/ACTIVITIES:
- To create reminders, use create_record with model='mail.activity'
- Required fields: activity_type_id (1=TODO, 2=Call, 3=Meeting), res_id, res_model, summary
- Optional: date_deadline (date string), user_id (assign to specific user)
- The system will automatically handle the res_model_id field

EXAMPLE 1 - Update Status (GOOD):
User: "@ai mark this as confirmed"
Your response: "{user_mention} ✅ I've confirmed this quotation. It's now a sales order."

EXAMPLE 1 - Update Status (BAD - DON'T DO THIS):
User: "@ai mark this as confirmed"
Bad response: "Ah I see, let me update the user on the actions I've taken: @User, I've confirmed the quotation."

EXAMPLE 2 - Create Reminder (GOOD):
User: "@ai remind me to call this client next week"
Your response: "{user_mention} ✅ I've created a reminder to call this client next week."

EXAMPLE 2 - Create Reminder (BAD - DON'T DO THIS):
User: "@ai remind me to call this client next week"
Bad response: "Let me create that reminder for you. @User I've now created an activity for calling the client."

Available tools:
- search_records: Query Odoo data
- create_record: Create new records (including mail.activity for reminders)
- write_record: Update existing records
- read_record: Read specific record data
- generate_graph: Create visualizations

Respond in {target_user.lang}."""

        return prompt
