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

    def _send_typing_notification(self, is_typing, ai_bot=None):
        """
        Helper method to send typing notifications to all channel members

        :param is_typing: Boolean indicating if AI is typing
        :param ai_bot: res.partner record for AI bot (optional, will be looked up if not provided)
        """
        try:
            if not ai_bot:
                ai_bot = self.env['res.partner'].sudo().search([
                    ('email', '=', 'ai.assistant@odoo.local')
                ], limit=1)

            if not ai_bot:
                return

            # Get all channel members (partners)
            member_partners = self.channel_partner_ids

            # Send to each channel member
            for partner in member_partners:
                self.env['bus.bus']._sendone(partner, 'mail.channel.partner/typing_status', {
                    'channel_id': self.id,
                    'partner_id': ai_bot.id,
                    'is_typing': is_typing,
                })

            # Also send to the channel itself for good measure
            self.env['bus.bus']._sendone(self, 'mail.channel.partner/typing_status', {
                'channel_id': self.id,
                'partner_id': ai_bot.id,
                'is_typing': is_typing,
            })

            _logger.info(f"Typing notification {'started' if is_typing else 'stopped'} for channel {self.id} to {len(member_partners)} members")
        except Exception as e:
            _logger.warning(f"Could not send typing notification: {e}")

    @api.model
    def create(self, vals):
        """Mark channels with AI bot as AI channels"""
        channel = super().create(vals)

        # If channel is already marked as AI channel and has a session, skip
        if channel.is_ai_channel and channel.ai_session_id:
            return channel

        # Check if channel includes AI bot partner and mark as AI channel
        ai_bot = self.env['res.partner'].sudo().search([
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
        """Override to intercept messages to AI bot"""
        message = super().message_post(**kwargs)

        # Skip processing if message has no author to prevent recursion
        if not message.author_id:
            return message

        # Get AI bot partner (search by email to handle name changes)
        ai_bot = self.env['res.partner'].sudo().search([
            ('email', '=', 'ai.assistant@odoo.local')
        ], limit=1)

        if not ai_bot:
            return message

        # Don't process messages FROM the AI bot (prevent recursion)
        if message.author_id.id == ai_bot.id:
            return message

        # Check if AI should respond in this channel:
        # 1. Channel is explicitly marked as AI channel (backward compatibility) - always respond
        # 2. 1-on-1 chat with AI (only 2 members) - always respond
        # 3. Group chat (3+ members) - ONLY respond when @mentioned
        # This prevents AI from responding to every message in group chats and overloading the system

        ai_is_member = ai_bot.id in self.channel_partner_ids.ids
        ai_is_mentioned = ai_bot.id in message.partner_ids.ids
        member_count = len(self.channel_partner_ids)
        is_direct_message = member_count == 2 and ai_is_member  # 1-on-1 chat with AI
        is_group_chat = member_count >= 3

        # Decision logic:
        # - is_ai_channel: Always respond (backward compatibility for dedicated AI channels)
        # - Direct message: Always respond (1-on-1 with AI)
        # - Group chat: Only respond when @mentioned
        if self.is_ai_channel:
            should_respond = True
        elif is_direct_message:
            should_respond = True
        elif is_group_chat:
            should_respond = ai_is_mentioned
        else:
            # Fallback: only respond if @mentioned
            should_respond = ai_is_mentioned

        _logger.info(f"message_post on channel {self.id} ({self.name}): members={member_count}, ai_member={ai_is_member}, ai_mentioned={ai_is_mentioned}, is_ai_channel={self.is_ai_channel}, is_dm={is_direct_message}, is_group={is_group_chat}, should_respond={should_respond}")

        if should_respond:
            import time
            start_time = time.time()
            _logger.info(f"[TIMING] Message received at {start_time}, starting async thread")
            # Get message content before starting thread (avoid cursor issues)
            message_body = message.body or ''
            _logger.info(f"Thread params: dbname={self.env.cr.dbname}, uid={self.env.uid}, channel_id={self.id}, message_body_length={len(message_body)}")
            # Process AI message asynchronously to avoid blocking the UI
            # Use threading to process in background with a new cursor
            thread = threading.Thread(
                target=self._process_ai_message_async,
                args=(self.env.cr.dbname, self.env.uid, self.id, message_body, start_time)
            )
            thread.daemon = True
            thread.start()
            thread_start_time = time.time()
            _logger.info(f"[TIMING] Async thread started at {thread_start_time}, thread start delay: {thread_start_time - start_time:.3f}s")

        return message

    def _format_ai_message_body(self, content, graph_data=None):
        """Format AI message content as HTML for proper display in Discuss

        Args:
            content: Text content to format
            graph_data: Optional dict with graph image data (base64)
        """
        from markupsafe import Markup

        if not content and not graph_data:
            return ''

        # Build HTML manually to avoid escaping issues
        # Convert newlines to <br/> tags for proper formatting
        if content:
            # Escape any HTML in the content text to prevent injection
            import html
            escaped_content = html.escape(content)
            # Convert newlines to <br/> tags
            html_content = escaped_content.replace('\n', '<br/>')
        else:
            html_content = ''

        # Embed graph if provided - this HTML should NOT be escaped
        if graph_data and graph_data.get('image_base64'):
            # Add graph image inline
            graph_html = f'<div style="margin: 15px 0;"><img src="data:image/png;base64,{graph_data["image_base64"]}" style="max-width: 100%; height: auto; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);" alt="Generated Graph"/></div>'
            html_content = html_content + graph_html

        # Mark as safe HTML so Odoo doesn't escape it
        return Markup(html_content)

    def _process_ai_message_async(self, dbname, uid, channel_id, message_body, start_time=None):
        """Process AI message asynchronously in a separate thread with new cursor"""
        import time
        async_start = time.time()
        if start_time:
            _logger.info(f"[TIMING] Async method started, delay from message_post: {async_start - start_time:.3f}s")
        _logger.info(f"[ASYNC] Starting async processing for channel {channel_id}")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Create a new registry and cursor for this thread
                import odoo
                registry = odoo.registry(dbname)
                _logger.info(f"[ASYNC] Registry obtained for {dbname}, attempt {attempt + 1}/{max_retries}")

                with registry.cursor() as cr:
                    _logger.info(f"[ASYNC] New cursor created")
                    env = api.Environment(cr, uid, {})
                    channel = env['mail.channel'].browse(channel_id)

                    _logger.info(f"[ASYNC] About to process message: {message_body[:50] if message_body else 'NO BODY'}")

                    # Process the AI message
                    channel._process_ai_message(message_body)

                    # Commit the transaction
                    cr.commit()
                    end_time = time.time()
                    total_time = end_time - async_start
                    if start_time:
                        total_from_message = end_time - start_time
                        _logger.info(f"[TIMING] Total processing time: {total_time:.2f}s, Total from message_post: {total_from_message:.2f}s")
                    _logger.info(f"[ASYNC] Processing complete and committed on attempt {attempt + 1}")
                    break  # Success! Exit the retry loop

            except Exception as e:
                error_msg = str(e)
                if 'could not serialize access' in error_msg or 'current transaction is aborted' in error_msg:
                    if attempt < max_retries - 1:
                        _logger.warning(f"[ASYNC] Serialization error on attempt {attempt + 1}/{max_retries}, retrying...")
                        import time
                        time.sleep(0.1 * (2 ** attempt))  # Exponential backoff: 0.1s, 0.2s, 0.4s
                        continue  # Retry
                    else:
                        _logger.error(f"[ASYNC] Serialization error after {max_retries} attempts, giving up")
                        # Post error message in a new transaction
                        self._post_async_error(dbname, uid, channel_id, "I'm experiencing database conflicts. Please try again.")
                        return
                else:
                    # Non-serialization error, don't retry
                    _logger.exception(f"[ASYNC] Error in async AI message processing: {e}")
                    self._post_async_error(dbname, uid, channel_id, str(e))
                    return

    def _post_async_error(self, dbname, uid, channel_id, error_message):
        """Post error message in a new transaction"""
        try:
            import odoo
            registry = odoo.registry(dbname)
            with registry.cursor() as cr:
                env = api.Environment(cr, uid, {})
                channel = env['mail.channel'].browse(channel_id)
                ai_bot = env['res.partner'].sudo().search([
                    ('email', '=', 'ai.assistant@odoo.local')
                ], limit=1)

                if ai_bot:
                    # Stop typing indicator
                    # Note: Can't use helper method here because of different env context
                    try:
                        # Send to all channel members
                        member_partners = channel.channel_partner_ids
                        for partner in member_partners:
                            env['bus.bus']._sendone(partner, 'mail.channel.partner/typing_status', {
                                'channel_id': channel.id,
                                'partner_id': ai_bot.id,
                                'is_typing': False,
                            })
                        # Also send to channel itself
                        env['bus.bus']._sendone(channel, 'mail.channel.partner/typing_status', {
                            'channel_id': channel.id,
                            'partner_id': ai_bot.id,
                            'is_typing': False,
                        })
                    except Exception:
                        pass

                    error_msg = f"Sorry, I encountered an error: {error_message}"
                    posted_message = channel.message_post(
                        body=channel._format_ai_message_body(error_msg),
                        author_id=ai_bot.id,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment'
                    )

                    # Commit first, then Odoo will automatically send bus notifications
                    cr.commit()
                    _logger.info(f"[ASYNC] Error message posted and committed successfully")

                    # NOTE: Removed manual bus notification - it was being sent before commit,
                    # causing race condition where Discuss couldn't fetch the message yet
        except Exception as post_error:
            _logger.exception(f"[ASYNC] Failed to post error message: {post_error}")

    def _process_ai_message(self, user_message_body):
        """Process user message and generate AI response

        Args:
            user_message_body: String content of the user's message
        """
        thinking_message = None
        try:
            # Get AI bot
            ai_bot = self.env['res.partner'].sudo().search([
                ('email', '=', 'ai.assistant@odoo.local')
            ], limit=1)

            if ai_bot:
                # Send typing indicator IMMEDIATELY and commit so user sees it right away
                self._send_typing_notification(True, ai_bot)
                # CRITICAL: Commit immediately so typing indicator appears in UI
                self.env.cr.commit()

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

            # Summarize conversation history if too long to prevent API errors
            # Increased threshold from 20 to 30 to reduce summarization overhead
            # Summarization adds 1-3 seconds per request
            if len(messages) > 30:
                _logger.info(f"Conversation long ({len(messages)} messages), creating summary")
                messages = self._summarize_conversation(messages, openrouter_api_key, openrouter_model)

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
                    mcp_server = self.env['mcp.server.registry'].sudo()
                    mcp_tools = mcp_server.list_tools()

                    # Convert MCP tools to OpenRouter/OpenAI format
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
                    _logger.info(f"Loaded {len(tools)} MCP tools")
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
                    _logger.info(f"AI response includes {len(tool_calls)} tool calls, processing them")
                    # Process tool calls and get final response
                    self._process_tool_calls(
                        session,
                        tool_calls,
                        content,
                        openrouter_api_key,
                        openrouter_model,
                        system_prompt,
                        tools,
                        thinking_message  # Pass thinking message to be deleted later
                    )
                else:
                    _logger.info(f"AI response has no tool calls, posting directly to channel")
                    # Create assistant message
                    self.env['ai.chat.message'].create({
                        'session_id': session.id,
                        'role': 'assistant',
                        'content': content,
                    })

                    # Delete thinking message before posting real response
                    if thinking_message:
                        try:
                            self.env.cr.execute('SAVEPOINT delete_thinking')
                            try:
                                # thinking_message is now an ID, need to browse it
                                msg_to_delete = self.env['mail.message'].browse(thinking_message)
                                if msg_to_delete.exists():
                                    msg_to_delete.unlink()
                                    _logger.info(f"Deleted thinking message {thinking_message}")
                                self.env.cr.execute('RELEASE SAVEPOINT delete_thinking')
                            except Exception as e:
                                _logger.warning(f"Could not delete thinking message: {e}")
                                self.env.cr.execute('ROLLBACK TO SAVEPOINT delete_thinking')
                                self.env.cr.execute('RELEASE SAVEPOINT delete_thinking')
                        except Exception:
                            pass  # Savepoint itself failed, just continue

                    # Post AI response to channel
                    ai_bot = self.env['res.partner'].sudo().search([
                        ('email', '=', 'ai.assistant@odoo.local')
                    ], limit=1)

                    if ai_bot:
                        # Stop typing indicator
                        self._send_typing_notification(False, ai_bot)

                        # Format the message body for proper display in Discuss
                        formatted_body = self._format_ai_message_body(content)
                        posted_message = self.message_post(
                            body=formatted_body,
                            author_id=ai_bot.id,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment'
                        )
                        # Commit - Odoo will send bus notifications automatically after commit
                        self.env.cr.commit()
                        _logger.info(f"Posted AI message {posted_message.id} to channel {self.id} and committed")

        except Exception as e:
            _logger.error(f"Error processing AI message: {e}", exc_info=True)
            # Delete thinking message on error
            if thinking_message:
                try:
                    self.env.cr.execute('SAVEPOINT delete_thinking_error')
                    try:
                        # thinking_message is now an ID, need to browse it
                        msg_to_delete = self.env['mail.message'].browse(thinking_message)
                        if msg_to_delete.exists():
                            msg_to_delete.unlink()
                            _logger.info(f"Deleted thinking message due to error")
                        self.env.cr.execute('RELEASE SAVEPOINT delete_thinking_error')
                    except Exception as del_error:
                        _logger.warning(f"Could not delete thinking message on error: {del_error}")
                        try:
                            self.env.cr.execute('ROLLBACK TO SAVEPOINT delete_thinking_error')
                            self.env.cr.execute('RELEASE SAVEPOINT delete_thinking_error')
                        except Exception:
                            pass  # Transaction may already be aborted
                except Exception:
                    pass  # Savepoint itself failed, just continue

            # Post error message to channel with AI bot as author to prevent recursion
            try:
                ai_bot = self.env['res.partner'].sudo().search([
                    ('email', '=', 'ai.assistant@odoo.local')
                ], limit=1)

                if ai_bot:
                    # Stop typing indicator on error
                    self._send_typing_notification(False, ai_bot)

                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    formatted_error = self._format_ai_message_body(error_message)
                    posted_message = self.with_context(mail_create_nosubscribe=True).message_post(
                        body=formatted_error,
                        author_id=ai_bot.id,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment'
                    )

                    # NOTE: Removed manual bus notification - Odoo handles this automatically on commit
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

WHEN CONTEXT IS UNCLEAR - ASK FOR CLARIFICATION:
- If a request is ambiguous or lacks necessary details, ASK clarifying questions BEFORE taking action
- Examples of when to ask:
  * "Create a quotation" → Ask: "For which customer? What products or services should I include?"
  * "Update this record" (in group chat) → Ask: "Which record are you referring to?"
  * "Change the status" → Ask: "Which record? What status should I set?"
  * Vague references like "this", "that", "it" without clear context → Ask for specifics
- In GROUP CHATS especially, be extra careful about context:
  * Messages may reference previous conversations you haven't seen
  * Multiple people may be discussing different topics
  * "This quotation" without a specific ID or clear reference → Ask which one
- NEVER guess or assume what the user wants - it's better to ask than to make a mistake
- Be concise in your questions - one or two specific questions max

CRITICAL INSTRUCTIONS FOR TOOL USAGE:
- You MUST complete ALL parts of multi-step tasks before providing a final response
- If a user asks you to create multiple records (e.g., customer + project + stages), you MUST call create_record for EACH item
- DO NOT respond with text like "Now I will create..." - actually execute the create_record tool
- Continue using tools until the ENTIRE task is complete
- Only provide a summary response AFTER all operations are finished

ERROR HANDLING AND DUPLICATES:
- When a tool call fails (e.g., duplicate record), CONTINUE with other tasks
- Complete everything you CAN complete
- In your final response:
  1. List what was created successfully
  2. Clearly explain what failed and WHY (e.g., "Tag 'Bug' already exists")
  3. Ask the user for clarification on failed items (e.g., "Would you like me to use the existing 'Bug' tag or create a different one?")
- NEVER let one failure stop the entire workflow
- Be transparent about partial success

EXAMPLE - Handling duplicates:
User: "Create project X with stages A, B, C and tags Bug, Feature"
→ Project X created successfully ✅
→ Stage A created ✅
→ Stage B created ✅
→ Stage C created ✅
→ Tag "Bug" failed: already exists ❌
→ Tag "Feature" created ✅

CORRECT response:
"I've created:
✅ Project 'X' (ID: 123)
✅ Stages: A, B, C
✅ Tag: Feature
❌ Tag 'Bug' already exists in the system

Would you like me to:
1. Link the existing 'Bug' tag to your project?
2. Create a new tag with a different name (e.g., 'Bug Fix')?
3. Skip this tag?"

GENERAL INSTRUCTIONS:
- Respond in the user's language ({user.lang})
- Use available tools to access and manipulate Odoo data
- Be concise and professional
- Provide clear, actionable answers based on real data

Available tools:
- search_records: Query Odoo data (sales, customers, products, etc.)
- create_record: Create new records (use this for EVERY record that needs to be created)
- write_record: Update existing records
- generate_graph: Create visualizations when explicitly requested

EXAMPLE - Multi-step task handling:
User: "Create customer ACME and a project for them with 3 stages"
CORRECT behavior:
  1. Call create_record for res.partner (customer)
  2. Call create_record for project.project (project)
  3. Call create_record for project.task.type (stage 1)
  4. Call create_record for project.task.type (stage 2)
  5. Call create_record for project.task.type (stage 3)
  6. Then respond: "Done! I created customer ACME, project X, and 3 stages"

WRONG behavior:
  1. Call create_record for res.partner
  2. Respond: "Customer created. Now I will create the project..." ← NEVER DO THIS!

Remember: Execute ALL required tool calls before providing a final text response."""

        return prompt

    def _summarize_conversation(self, messages, api_key, model):
        """Summarize older messages when conversation gets too long

        This method creates a summary of older messages to reduce token usage
        while preserving recent context (similar to Claude's approach).

        Args:
            messages: List of conversation messages
            api_key: OpenRouter API key
            model: Model to use for summarization

        Returns:
            List of messages with summary + recent messages
        """
        try:
            # Keep last 10 messages intact for immediate context
            # Summarize everything before that
            recent_messages = messages[-10:]
            old_messages = messages[:-10]

            if not old_messages:
                # Nothing to summarize
                return messages

            # CRITICAL: Clean recent_messages to avoid orphaned tool sequences
            # Remove orphaned tool messages from start (tool without preceding assistant)
            while recent_messages and recent_messages[0].get('role') == 'tool':
                _logger.info(f"Removing orphaned tool message from start of recent messages")
                # Move this orphaned tool message to old_messages so it gets summarized
                old_messages.append(recent_messages.pop(0))

            # Remove incomplete tool sequences from end (assistant with tool_calls but no results)
            if recent_messages and recent_messages[-1].get('role') == 'assistant' and recent_messages[-1].get('tool_calls'):
                _logger.info(f"Removing incomplete assistant+tool_calls from end of recent messages")
                # Move back to old_messages
                old_messages.append(recent_messages.pop())

            # If we removed too much, just return original messages
            if not recent_messages:
                _logger.warning("Recent messages became empty after cleanup, returning original")
                return messages

            # Create a summarization prompt
            summary_prompt = """Please create a concise summary of this conversation history. Focus on:
- Key topics discussed
- Important data queries or searches performed
- Records created or modified
- Decisions or conclusions reached

Keep the summary brief (2-3 paragraphs max) but include enough detail that the conversation can continue naturally."""

            # Build messages for summarization call
            summarization_messages = [
                {'role': 'system', 'content': summary_prompt}
            ]

            # Add old messages to summarize
            for msg in old_messages:
                # Skip tool messages in summary - they're too verbose
                if msg.get('role') == 'tool':
                    continue
                # Skip assistant messages with tool_calls - would be orphaned without tool results
                if msg.get('role') == 'assistant' and msg.get('tool_calls'):
                    continue
                summarization_messages.append(msg)

            _logger.info(f"Summarizing {len(old_messages)} old messages (keeping last 10 intact)")

            # Call API to get summary
            summary_response = self._call_openrouter_api(
                api_key,
                model,
                summarization_messages,
                tools=None  # No tools for summarization
            )

            if summary_response and summary_response.get('choices'):
                summary_text = summary_response['choices'][0]['message'].get('content', '')

                if summary_text:
                    # Create summary message and prepend to recent messages
                    summary_message = {
                        'role': 'system',
                        'content': f"[Previous conversation summary]\n{summary_text}\n[End of summary - continuing with recent messages]"
                    }

                    result_messages = [summary_message] + recent_messages
                    _logger.info(f"Created summary, reduced from {len(messages)} to {len(result_messages)} messages")
                    return result_messages
                else:
                    _logger.warning("Summarization returned empty content")
            else:
                _logger.warning("Summarization API call failed")

        except Exception as e:
            _logger.error(f"Error during conversation summarization: {e}")

        # Fallback: Two-pass validation to ensure complete tool sequences
        # Start with last 20 messages for more context
        truncated = messages[-20:] if len(messages) > 20 else messages

        # PASS 1: Build sets of available tool_use and tool_result IDs
        tool_use_ids = set()  # IDs requested by assistant messages
        tool_result_ids = set()  # IDs with results from tool messages

        for msg in truncated:
            # Collect tool_use IDs from assistant messages
            if msg.get('role') == 'assistant' and msg.get('tool_calls'):
                for tc in msg.get('tool_calls', []):
                    tool_use_ids.add(tc.get('id'))

            # Collect tool_result IDs from tool messages
            elif msg.get('role') == 'tool':
                tool_call_id = msg.get('tool_call_id')
                if tool_call_id:
                    tool_result_ids.add(tool_call_id)

        _logger.info(f"Pass 1 complete: {len(tool_use_ids)} tool_uses, {len(tool_result_ids)} tool_results")

        # PASS 2: Build validated message list with complete sequences only
        validated = []

        for i, msg in enumerate(truncated):
            role = msg.get('role')

            # Rule 1: Skip assistant+tool_calls if ANY of its tools don't have results
            if role == 'assistant' and msg.get('tool_calls'):
                tool_calls = msg.get('tool_calls', [])
                all_have_results = all(tc.get('id') in tool_result_ids for tc in tool_calls)

                if not all_have_results:
                    missing = [tc.get('id') for tc in tool_calls if tc.get('id') not in tool_result_ids]
                    _logger.info(f"Skipping assistant at index {i} - missing tool_results for: {missing}")
                    continue

            # Rule 2: Skip tool_result if its tool_use doesn't exist
            elif role == 'tool':
                tool_call_id = msg.get('tool_call_id')
                if tool_call_id not in tool_use_ids:
                    _logger.info(f"Skipping orphaned tool_result at index {i} (tool_call_id: {tool_call_id})")
                    continue

            # Rule 3: Skip consecutive assistant messages (keep only last one)
            if role == 'assistant' and validated and validated[-1].get('role') == 'assistant':
                _logger.info(f"Replacing duplicate assistant at index {i}")
                validated.pop()

            validated.append(msg)

        # Post-processing cleanup
        # Remove any trailing incomplete sequences (shouldn't happen now but defensive)
        while validated and validated[-1].get('role') == 'assistant' and validated[-1].get('tool_calls'):
            _logger.info(f"Removing incomplete assistant+tool_calls from end")
            validated.pop()

        # Remove any leading tool messages (shouldn't happen now but defensive)
        while validated and validated[0].get('role') == 'tool':
            _logger.info(f"Removing leading tool_result")
            validated.pop(0)

        # Ensure we have at least one user message
        if not any(m.get('role') == 'user' for m in validated):
            _logger.error("No user messages in validated sequence, returning original last message")
            return [messages[-1]] if messages else []

        _logger.warning(f"Summarization failed, falling back to validated truncation: {len(messages)} -> {len(validated)} messages")
        return validated if validated else [messages[-1]] if messages else []

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

        # Log request details for debugging
        _logger.info(f"OpenRouter API call: {len(messages)} messages, tools={'yes' if tools else 'no'}")

        response = requests.post(url, headers=headers, json=payload, timeout=60)

        # Better error handling - log response body on error
        if not response.ok:
            try:
                error_body = response.json()
                _logger.error(f"OpenRouter API error ({response.status_code}): {error_body}")
            except Exception:
                _logger.error(f"OpenRouter API error ({response.status_code}): {response.text}")

        response.raise_for_status()

        return response.json()

    def _process_tool_calls(self, session, tool_calls, assistant_content, openrouter_api_key, openrouter_model, system_prompt, tools, thinking_message=None):
        """Process tool calls from AI and get final response

        This method implements a loop that allows the AI to make multiple rounds of tool calls
        until it completes the entire task. This is critical for multi-step operations like:
        - Creating customer + project + stages + tags
        - Searching for data, then updating multiple records based on results
        - Any workflow that requires sequential tool execution

        Args:
            thinking_message: The "AI is thinking..." message to delete before posting final response
        """
        _logger.info(f"Processing {len(tool_calls)} tool calls")

        # Track graph data across all iterations
        graph_data = None
        mcp_server = self.env['mcp.server.registry'].sudo()

        # Allow up to 10 iterations of tool calls to prevent infinite loops
        # Most tasks complete in 2-3 iterations, but complex workflows may need more
        max_iterations = 20  # Allow up to 20 rounds of tool calls
        iteration = 0

        # Keep calling AI until it stops making tool calls (task is complete)
        current_tool_calls = tool_calls
        current_content = assistant_content

        while current_tool_calls and iteration < max_iterations:
            iteration += 1
            _logger.info(f"Tool call iteration {iteration}/{max_iterations}, processing {len(current_tool_calls)} tool calls")

            # Create assistant message with tool calls
            tool_calls_data = []
            for tc in current_tool_calls:
                tool_calls_data.append({
                    'tool_call_id': tc['id'],
                    'name': tc['function']['name'],
                    'arguments': json.loads(tc['function']['arguments'])
                })

            self.env['ai.chat.message'].create({
                'session_id': session.id,
                'role': 'assistant',
                'content': current_content or '',
                'tool_calls': json.dumps(tool_calls_data),
            })

            # Execute all tool calls in this iteration
            for tc in current_tool_calls:
                # Use savepoint to isolate each tool execution
                # If one tool fails, we can rollback just that operation
                savepoint_name = f"tool_exec_{tc['id'][:8]}"

                try:
                    tool_name = tc['function']['name']
                    tool_args = json.loads(tc['function']['arguments'])

                    _logger.info(f"Executing tool: {tool_name} with args: {tool_args}")

                    # Create savepoint before tool execution
                    self.env.cr.execute(f'SAVEPOINT {savepoint_name}')

                    try:
                        result = mcp_server.call_tool(tool_name, tool_args)

                        # Extract graph data if this was a generate_graph call
                        if tool_name == 'generate_graph' and result.get('success') and result.get('image_base64'):
                            graph_data = {'image_base64': result['image_base64']}
                            _logger.info(f"Graph generated successfully, image size: {len(result['image_base64'])} chars")

                        # Tool succeeded - release savepoint
                        self.env.cr.execute(f'RELEASE SAVEPOINT {savepoint_name}')

                    except Exception as tool_error:
                        # Tool failed - rollback to savepoint
                        _logger.warning(f"Tool {tool_name} failed, rolling back to savepoint: {tool_error}")
                        self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {savepoint_name}')
                        self.env.cr.execute(f'RELEASE SAVEPOINT {savepoint_name}')

                        # Create error result
                        result = {'success': False, 'error': str(tool_error)}

                    # Create tool response message (outside savepoint)
                    self.env['ai.chat.message'].create({
                        'session_id': session.id,
                        'role': 'tool',
                        'content': json.dumps(result),
                        'tool_call_id': tc['id'],
                        'metadata': json.dumps({'tool_name': tool_name, 'error': not result.get('success', False)}),
                    })

                except Exception as e:
                    _logger.error(f"Critical error in tool execution loop for {tc.get('function', {}).get('name', 'unknown')}: {e}")
                    # Try to rollback savepoint if it exists
                    try:
                        self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {savepoint_name}')
                        self.env.cr.execute(f'RELEASE SAVEPOINT {savepoint_name}')
                    except Exception:
                        pass

                    # Create error response
                    error_result = {'success': False, 'error': str(e)}
                    try:
                        self.env['ai.chat.message'].create({
                            'session_id': session.id,
                            'role': 'tool',
                            'content': json.dumps(error_result),
                            'tool_call_id': tc['id'],
                            'metadata': json.dumps({'tool_name': tc.get('function', {}).get('name', 'unknown'), 'error': True}),
                        })
                    except Exception as msg_error:
                        _logger.error(f"Could not even create error message: {msg_error}")
                        # If we can't create the error message, the transaction is really broken
                        # This will be caught by the outer exception handler
                        raise

            # After executing tools, call AI again with results
            # IMPORTANT: Keep tools enabled so AI can make additional calls if needed
            _logger.info("Calling AI again with tool results (tools still enabled)")

            # Get updated messages including tool results
            messages = session.get_messages_for_api()

            # Summarize conversation if too long
            if len(messages) > 20:
                _logger.info(f"Conversation long ({len(messages)} messages) during tool loop, creating summary")
                messages = self._summarize_conversation(messages, openrouter_api_key, openrouter_model)

            messages.insert(0, {
                'role': 'system',
                'content': system_prompt
            })

            # Call AI again WITH tools enabled to allow multi-step operations
            try:
                next_response = self._call_openrouter_api(
                    openrouter_api_key,
                    openrouter_model,
                    messages,
                    tools=tools  # CRITICAL: Keep tools enabled for multi-step tasks!
                )

                if next_response and next_response.get('choices'):
                    next_message = next_response['choices'][0]['message']
                    current_content = next_message.get('content', '')
                    current_tool_calls = next_message.get('tool_calls')

                    # Check if AI wants to make more tool calls
                    if current_tool_calls:
                        _logger.info(f"AI wants to make {len(current_tool_calls)} more tool calls, continuing loop")
                        # Loop will continue with these new tool calls
                    else:
                        # No more tool calls - AI is done, this is the final response
                        _logger.info("AI provided final response with no more tool calls")
                        # Break out of loop to post the final message
                        break
                else:
                    _logger.warning("No response from AI after tool execution")
                    current_tool_calls = None
                    break

            except Exception as e:
                _logger.error(f"Error calling AI after tool execution: {e}")
                current_tool_calls = None
                current_content = f"I completed some operations but encountered an error: {str(e)}"
                break

        # After the loop completes, post the final response to the channel
        if iteration >= max_iterations:
            _logger.warning(f"Reached max iterations ({max_iterations}), stopping tool call loop")
            # Ask AI for a summary if we hit the limit
            if not current_content:
                try:
                    summary_messages = messages + [{
                        'role': 'system',
                        'content': f'You reached the maximum number of tool execution rounds ({max_iterations}). Please provide a brief summary of what you accomplished and what remains to be done.'
                    }]
                    summary_response = self._call_openrouter_api(
                        openrouter_api_key,
                        openrouter_model,
                        summary_messages,
                        tools=None
                    )
                    if summary_response and summary_response.get('choices'):
                        current_content = summary_response['choices'][0]['message'].get('content', '')
                except Exception as e:
                    _logger.error(f"Failed to get summary after max iterations: {e}")

            if not current_content:
                current_content = f"I completed {iteration} operations but reached the maximum number of steps allowed in one conversation turn. Please let me know if you'd like me to continue or if there's anything else I can help with."

        # Create final assistant message if we have content
        if current_content:
            self.env['ai.chat.message'].create({
                'session_id': session.id,
                'role': 'assistant',
                'content': current_content,
            })

        # Delete thinking message before posting real response
        if thinking_message:
            try:
                self.env.cr.execute('SAVEPOINT delete_thinking')
                try:
                    # thinking_message is now an ID, need to browse it
                    msg_to_delete = self.env['mail.message'].browse(thinking_message)
                    if msg_to_delete.exists():
                        msg_to_delete.unlink()
                        _logger.info(f"Deleted thinking message before posting final response")
                    self.env.cr.execute('RELEASE SAVEPOINT delete_thinking')
                except Exception as e:
                    _logger.warning(f"Could not delete thinking message: {e}")
                    self.env.cr.execute('ROLLBACK TO SAVEPOINT delete_thinking')
                    self.env.cr.execute('RELEASE SAVEPOINT delete_thinking')
            except Exception:
                pass  # Savepoint itself failed, just continue

        # Post final response to channel
        ai_bot = self.env['res.partner'].sudo().search([
            ('email', '=', 'ai.assistant@odoo.local')
        ], limit=1)

        if ai_bot:
            # Stop typing indicator
            self._send_typing_notification(False, ai_bot)

            if current_content:
                # Format body with graph if available
                formatted_body = self._format_ai_message_body(current_content, graph_data=graph_data)

                # Use context to prevent auto-updating channel member (seen/fetched fields)
                # This avoids concurrent update conflicts with user UI actions
                posted_message = self.with_context(
                    mail_create_nosubscribe=True,
                    mail_channel_noautofollow=True
                ).message_post(
                    body=formatted_body,
                    author_id=ai_bot.id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
                # Commit - Odoo will send bus notifications automatically after commit
                self.env.cr.commit()
                _logger.info(f"Posted final AI message {posted_message.id} to channel {self.id} after {iteration} iterations and committed")
