"""AI Chat Session Model"""

from odoo import api, fields, models


class AIChatSession(models.Model):
    """AI Chat Session - represents a conversation thread"""

    _name = 'ai.chat.session'
    _description = 'AI Chat Session'
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

    def get_messages_for_api(self):
        """Get messages formatted for AI API"""
        import json
        import logging
        _logger = logging.getLogger(__name__)

        self.ensure_one()
        messages = []

        for msg in self.message_ids.sorted('create_date'):
            # Skip tool messages without proper tool_call_id (backward compatibility)
            if msg.role == 'tool' and not msg.tool_call_id:
                _logger.warning(f"Skipping tool message {msg.id} without tool_call_id")
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
