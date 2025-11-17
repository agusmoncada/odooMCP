"""Extend res.users to auto-create AI channel for new users"""

from odoo import api, models
import logging

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    """Extend res.users to create AI Assistant channel for new users"""

    _inherit = 'res.users'

    @api.model
    def create(self, vals):
        """Create AI Assistant channel for new internal users"""
        user = super().create(vals)

        # Only create AI channel for internal users (not portal/public)
        if not user.share and user.active:
            try:
                # Create AI Assistant channel for this new user
                session_model = self.env['ai.chat.session'].sudo(user.id)
                channel = session_model.get_or_create_ai_channel_for_user()

                if channel:
                    _logger.info(f"AI Chat: Auto-created AI Assistant channel for new user {user.name} (ID: {user.id})")
            except Exception as e:
                _logger.error(f"AI Chat: Failed to auto-create AI channel for new user {user.name} (ID: {user.id}): {e}")

        return user
