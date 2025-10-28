"""AI Chat Message Model"""

from odoo import api, fields, models


class AIChatMessage(models.Model):
    """AI Chat Message - individual messages in a conversation"""

    _name = 'ai.chat.message'
    _description = 'AI Chat Message'
    _order = 'create_date asc'

    session_id = fields.Many2one(
        'ai.chat.session',
        string='Session',
        required=True,
        ondelete='cascade',
        index=True
    )

    role = fields.Selection(
        [
            ('user', 'User'),
            ('assistant', 'Assistant'),
            ('system', 'System'),
            ('tool', 'Tool')
        ],
        string='Role',
        required=True,
        default='user'
    )

    content = fields.Text(
        string='Content',
        required=True
    )

    tool_calls = fields.Text(
        string='Tool Calls',
        help='JSON data for tool calls made by the assistant'
    )

    tool_call_id = fields.Char(
        string='Tool Call ID',
        help='ID of the tool call this message responds to'
    )

    metadata = fields.Text(
        string='Metadata',
        help='Additional metadata in JSON format'
    )

    tokens_used = fields.Integer(
        string='Tokens Used',
        help='Number of tokens used for this message'
    )

    def name_get(self):
        """Display name for the message"""
        result = []
        for record in self:
            content_preview = record.content[:50]
            if len(record.content) > 50:
                content_preview += '...'
            name = f'[{record.role}] {content_preview}'
            result.append((record.id, name))
        return result
