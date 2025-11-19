"""AI Chat Session Model"""

from odoo import api, fields, models
import base64
import os


class AIChatSession(models.Model):
    """AI Chat Session - represents a conversation thread"""

    _name = 'ai.chat.session'
    _description = 'AI Chat Session'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char(
        string='Session Name',
        required=True,
        default='New Chat'
    )

    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        default=lambda self: self.env.user,
        ondelete='cascade'
    )

    channel_id = fields.Many2one(
        'mail.channel',
        string='Discuss Channel',
        help='Linked Discuss channel for this session',
        ondelete='set null'
    )

    chat_message_ids = fields.One2many(
        'ai.chat.message',
        'session_id',
        string='Chat Messages'
    )

    message_count = fields.Integer(
        string='Message Count',
        compute='_compute_message_count',
        store=True
    )

    last_message_date = fields.Datetime(
        string='Last Message',
        compute='_compute_last_message_date',
        store=True
    )

    active = fields.Boolean(
        string='Active',
        default=True
    )

    @api.depends('chat_message_ids')
    def _compute_message_count(self):
        for session in self:
            session.message_count = len(session.chat_message_ids)

    @api.depends('chat_message_ids.create_date')
    def _compute_last_message_date(self):
        for session in self:
            if session.chat_message_ids:
                session.last_message_date = max(
                    session.chat_message_ids.mapped('create_date')
                )
            else:
                session.last_message_date = False

    def action_archive(self):
        """Archive this chat session"""
        self.write({'active': False})

    def action_unarchive(self):
        """Unarchive this chat session"""
        self.write({'active': True})

    def _get_ai_bot_partner(self):
        """Get or create AI bot partner with user account

        The AI bot needs a user account to:
        - Appear in Discuss contacts
        - Be added to group chats
        - Participate in conversations

        The bot appears as a contact in Discuss that you can:
        - Start 1-on-1 chats with
        - Add to group conversations
        - @mention in any channel
        """
        # Check if AI user already exists
        ai_user = self.env['res.users'].sudo().search([
            ('login', '=', 'ai.assistant@odoo.local')
        ], limit=1)

        # Read AI icon from module's static folder
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'static', 'description', 'icon.png'
        )

        image_data = False
        if os.path.exists(icon_path):
            with open(icon_path, 'rb') as icon_file:
                image_data = base64.b64encode(icon_file.read())

        if not ai_user:
            # Check for old partner-only bot (migration from previous version)
            old_partner_bot = self.env['res.partner'].sudo().search([
                ('email', '=', 'ai.assistant@odoo.local'),
                ('user_ids', '=', False)  # Partner without user
            ], limit=1)

            # Create AI user (this automatically creates the partner or links to existing one)
            # Use internal user to avoid portal limitations
            create_vals = {
                'name': 'AI Assistant',
                'login': 'ai.assistant@odoo.local',
                'email': 'ai.assistant@odoo.local',
                'active': True,
                'image_1920': image_data,
                'notification_type': 'inbox',
                'odoobot_state': 'disabled',  # Disable OdooBot tips
                # Use minimal groups to avoid consuming license
                'groups_id': [(6, 0, [
                    self.env.ref('base.group_user').id,  # Internal user (needed for Discuss)
                ])],
            }

            # If old partner exists, link to it instead of creating new partner
            if old_partner_bot:
                create_vals['partner_id'] = old_partner_bot.id

            ai_user = self.env['res.users'].sudo().create(create_vals)

            # Update partner with additional info
            ai_user.partner_id.sudo().write({
                'im_status': 'online',
                'type': 'contact',
                'comment': 'AI Assistant - Ask me anything about your Odoo data! You can DM me, add me to groups, or @mention me.',
            })
        else:
            # Update existing user's partner
            update_vals = {
                'name': 'AI Assistant',
                'im_status': 'online',
                'active': True,
                'comment': 'AI Assistant - Ask me anything about your Odoo data! You can DM me, add me to groups, or @mention me.',
            }
            if image_data and not ai_user.partner_id.image_1920:
                update_vals['image_1920'] = image_data
            ai_user.partner_id.sudo().write(update_vals)

        return ai_user.partner_id

    def action_create_discuss_channel(self):
        """Create or link to a Discuss channel"""
        self.ensure_one()

        if self.channel_id:
            # Channel already exists, just open it
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mail.channel',
                'res_id': self.channel_id.id,
                'view_mode': 'form',
                'target': 'current',
            }

        # Create new AI channel
        ai_bot = self._get_ai_bot_partner()

        channel = self.env['mail.channel'].create({
            'name': f'AI Assistant: {self.name}',
            'description': f'AI chat session linked to {self.name}',
            'channel_type': 'chat',
            'channel_partner_ids': [
                (4, self.env.user.partner_id.id),
                (4, ai_bot.id)
            ],
        })

        self.channel_id = channel

        # Sync existing messages to the channel
        for msg in self.chat_message_ids.filtered(lambda m: m.role in ('user', 'assistant')):
            author = self.env.user.partner_id if msg.role == 'user' else ai_bot
            channel.message_post(
                body=msg.content,
                author_id=author.id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment'
            )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mail.channel',
            'res_id': channel.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def get_or_create_ai_channel_for_user(self):
        """Get or create a personal AI channel for the current user"""
        ai_bot = self._get_ai_bot_partner()

        # Look for existing AI channel - a chat with both the user and AI bot
        channel = self.env['mail.channel'].search([
            ('channel_type', '=', 'chat'),
            ('is_ai_channel', '=', True),
            ('channel_partner_ids', 'in', [self.env.user.partner_id.id])
        ], limit=1)

        if channel:
            return channel

        # Create new AI channel
        channel = self.env['mail.channel'].create({
            'name': f'AI Assistant',
            'description': 'Personal AI Assistant powered by IT Patagon',
            'channel_type': 'chat',
            'is_ai_channel': True,  # Explicitly set this flag
            'channel_partner_ids': [
                (4, self.env.user.partner_id.id),
                (4, ai_bot.id)
            ],
        })

        # Create linked AI session
        session = self.create({
            'name': 'AI Assistant Chat',
            'user_id': self.env.user.id,
            'channel_id': channel.id,
        })
        channel.ai_session_id = session.id

        return channel

    def create_new_ai_channel_for_user(self, name=None):
        """Create a new AI channel for the current user (allows multiple sessions)"""
        ai_bot = self._get_ai_bot_partner()
        
        # Generate a unique name if not provided
        if not name:
            # Count existing AI channels for this user
            existing_count = self.env['mail.channel'].search_count([
                ('channel_type', '=', 'chat'),
                ('is_ai_channel', '=', True),
                ('channel_partner_ids', 'in', [self.env.user.partner_id.id])
            ])
            name = f'AI Assistant #{existing_count + 1}'

        # Create new AI channel
        channel = self.env['mail.channel'].create({
            'name': name,
            'description': 'Personal AI Assistant powered by IT Patagon',
            'channel_type': 'chat',
            'is_ai_channel': True,
            'channel_partner_ids': [
                (4, self.env.user.partner_id.id),
                (4, ai_bot.id)
            ],
        })

        # Create linked AI session
        session = self.create({
            'name': name,
            'user_id': self.env.user.id,
            'channel_id': channel.id,
        })
        channel.ai_session_id = session.id

        return channel

    def get_user_ai_channels(self):
        """Get all AI channels for the current user"""
        return self.env['mail.channel'].search([
            ('channel_type', '=', 'chat'),
            ('is_ai_channel', '=', True),
            ('channel_partner_ids', 'in', [self.env.user.partner_id.id])
        ], order='create_date desc')

    def get_messages_for_api(self, max_messages=None):
        """Get messages formatted for AI API"""
        import json
        import logging
        _logger = logging.getLogger(__name__)

        self.ensure_one()
        messages = []

        # Apply message limit if specified
        chat_messages = self.chat_message_ids.sorted('create_date')
        if max_messages and max_messages > 0:
            # Keep only the most recent messages
            total_messages = len(chat_messages)
            if total_messages > max_messages:
                chat_messages = chat_messages[-max_messages:]
                _logger.info(f"Limited conversation history to {max_messages} messages (was {total_messages})")

        # PASS 1: Track which tool_call_ids have responses
        tool_call_ids_with_responses = set()
        for msg in chat_messages:
            if msg.role == 'tool' and msg.tool_call_id:
                tool_call_ids_with_responses.add(msg.tool_call_id)

        # PASS 2: Build valid tool_call_ids (only from assistant messages that will be included)
        valid_tool_call_ids = set()
        for msg in chat_messages:
            if msg.role == 'assistant' and msg.tool_calls:
                try:
                    tool_calls_data = json.loads(msg.tool_calls)
                    if tool_calls_data:
                        # Check if ALL tool calls have responses
                        all_have_responses = all(
                            tc.get('tool_call_id') in tool_call_ids_with_responses
                            for tc in tool_calls_data
                        )

                        if all_have_responses:
                            # This assistant message will be included, so mark its tool_call_ids as valid
                            for tc in tool_calls_data:
                                if tc.get('tool_call_id'):
                                    valid_tool_call_ids.add(tc['tool_call_id'])
                except (json.JSONDecodeError, KeyError):
                    pass

        # PASS 3: Build messages array, only including tool results with valid tool_call_ids
        for msg in chat_messages:
            # Skip tool messages without proper tool_call_id (backward compatibility)
            if msg.role == 'tool' and not msg.tool_call_id:
                _logger.warning(f"Skipping tool message {msg.id} without tool_call_id")
                continue

            # Skip tool messages whose assistant message was excluded (prevents orphaned tool results)
            if msg.role == 'tool' and msg.tool_call_id not in valid_tool_call_ids:
                _logger.warning(f"Skipping tool message {msg.id} with tool_call_id {msg.tool_call_id} - corresponding assistant message not included")
                continue

            message_dict = {
                'role': msg.role,
                'content': msg.content or ''
            }

            # Add tool_calls for assistant messages that called tools
            if msg.role == 'assistant' and msg.tool_calls:
                try:
                    tool_calls_data = json.loads(msg.tool_calls)
                    if tool_calls_data:
                        # Check if ALL tool calls have responses
                        all_have_responses = all(
                            tc.get('tool_call_id') in tool_call_ids_with_responses
                            for tc in tool_calls_data
                        )

                        if not all_have_responses:
                            # Skip this assistant message - incomplete tool execution
                            missing_ids = [tc.get('tool_call_id') for tc in tool_calls_data
                                         if tc.get('tool_call_id') not in tool_call_ids_with_responses]
                            _logger.warning(f"Skipping assistant message {msg.id} with incomplete tool calls. Missing responses for: {missing_ids}")
                            # Also remove the orphaned tool_call_ids from valid set
                            for tc in tool_calls_data:
                                if tc.get('tool_call_id') in valid_tool_call_ids:
                                    valid_tool_call_ids.discard(tc.get('tool_call_id'))
                            continue

                        # Format tool calls for OpenAI API
                        message_dict['tool_calls'] = []
                        for tool_call in tool_calls_data:
                            message_dict['tool_calls'].append({
                                'id': tool_call['tool_call_id'],
                                'type': 'function',
                                'function': {
                                    'name': tool_call['name'],
                                    'arguments': json.dumps(tool_call['arguments'])
                                }
                            })
                except (json.JSONDecodeError, KeyError, TypeError):
                    # If we can't parse tool_calls, don't include them
                    pass

            # Add tool_call_id for tool response messages
            elif msg.role == 'tool' and msg.tool_call_id:
                message_dict['tool_call_id'] = msg.tool_call_id

                # Extract tool name from metadata - REQUIRED by OpenRouter
                tool_name = None
                if msg.metadata:
                    try:
                        metadata = json.loads(msg.metadata)
                        tool_name = metadata.get('tool_name')
                        _logger.info(f"Tool message {msg.id} metadata: {metadata}, tool_name: {tool_name}")
                    except json.JSONDecodeError as e:
                        _logger.error(f"Failed to parse metadata for tool message {msg.id}: {e}")
                else:
                    _logger.warning(f"Tool message {msg.id} has no metadata")

                # Skip tool messages without name (backward compatibility)
                if not tool_name:
                    _logger.warning(f"Skipping tool message {msg.id} without tool_name")
                    continue

                message_dict['name'] = tool_name

            messages.append(message_dict)

        _logger.info(f"Returning {len(messages)} messages for API")
        for i, msg in enumerate(messages):
            _logger.info(f"Message[{i}]: role={msg.get('role')}, has_tool_calls={bool(msg.get('tool_calls'))}, has_tool_call_id={bool(msg.get('tool_call_id'))}, has_name={bool(msg.get('name'))}")

        return messages
