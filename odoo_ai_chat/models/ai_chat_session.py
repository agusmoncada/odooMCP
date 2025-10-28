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
        self.ensure_one()
        messages = []

        for msg in self.message_ids.sorted('create_date'):
            messages.append({
                'role': msg.role,
                'content': msg.content
            })

        return messages
