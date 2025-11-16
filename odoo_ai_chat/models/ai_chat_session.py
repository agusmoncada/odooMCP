"""AI Chat Session Model"""

from odoo import api, fields, models


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

    message_ids = fields.One2many(
        'ai.chat.message',
        'session_id',
        string='Messages'
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

    @api.depends('message_ids')
    def _compute_message_count(self):
        for session in self:
            session.message_count = len(session.message_ids)

    @api.depends('message_ids.create_date')
    def _compute_last_message_date(self):
        for session in self:
            if session.message_ids:
                session.last_message_date = max(
                    session.message_ids.mapped('create_date')
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
        """Get or create AI bot partner"""
        bot = self.env['res.partner'].sudo().search([
            ('name', '=', 'AI Assistant Bot'),
            ('email', '=', 'ai.assistant@odoo.local')
        ], limit=1)

        if not bot:
            bot = self.env['res.partner'].sudo().create({
                'name': 'AI Assistant Bot',
                'email': 'ai.assistant@odoo.local',
                'active': True,
                'is_company': False,
                'type': 'contact',
            })

        return bot

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
            'public': 'private',
            'email_send': False,
            'channel_partner_ids': [
                (4, self.env.user.partner_id.id),
                (4, ai_bot.id)
            ],
        })

        self.channel_id = channel

        # Sync existing messages to the channel
        for msg in self.message_ids.filtered(lambda m: m.role in ('user', 'assistant')):
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
        # Look for existing AI channel
        channel = self.env['mail.channel'].search([
            ('name', '=', f'AI Assistant - {self.env.user.name}'),
            ('channel_partner_ids', 'in', [self.env.user.partner_id.id])
        ], limit=1)

        if channel:
            return channel

        # Create new AI channel
        ai_bot = self._get_ai_bot_partner()

        channel = self.env['mail.channel'].create({
            'name': f'AI Assistant - {self.env.user.name}',
            'description': 'Personal AI Assistant powered by OpenRouter',
            'public': 'private',
            'email_send': False,
            'channel_type': 'chat',
            'channel_partner_ids': [
                (4, self.env.user.partner_id.id),
                (4, ai_bot.id)
            ],
        })

        return channel

    def get_messages_for_api(self):
        """Get messages formatted for AI API"""
        import json
        import logging
        _logger = logging.getLogger(__name__)

        self.ensure_one()
        messages = []

        # Track which tool_call_ids have responses AND which were requested
        tool_call_ids_with_responses = set()
        tool_call_ids_requested = set()

        for msg in self.message_ids:
            if msg.role == 'tool' and msg.tool_call_id:
                tool_call_ids_with_responses.add(msg.tool_call_id)
            elif msg.role == 'assistant' and msg.tool_calls:
                try:
                    tool_calls_data = json.loads(msg.tool_calls)
                    for tc in tool_calls_data:
                        if tc.get('tool_call_id'):
                            tool_call_ids_requested.add(tc['tool_call_id'])
                except (json.JSONDecodeError, KeyError):
                    pass

        for msg in self.message_ids.sorted('create_date'):
            # Skip tool messages without proper tool_call_id (backward compatibility)
            if msg.role == 'tool' and not msg.tool_call_id:
                _logger.warning(f"Skipping tool message {msg.id} without tool_call_id")
                continue

            # Skip orphaned tool messages (tool_call_id not requested by any assistant message)
            if msg.role == 'tool' and msg.tool_call_id not in tool_call_ids_requested:
                _logger.warning(f"Skipping orphaned tool message {msg.id} with tool_call_id {msg.tool_call_id} - no corresponding assistant message")
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
