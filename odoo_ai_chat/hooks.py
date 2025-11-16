"""Post-installation hooks for AI Chat module"""

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(cr, registry):
    """Create AI Assistant channels for all existing users after module installation"""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    _logger.info("AI Chat: Creating AI Assistant channels for all users...")

    # Get all active internal users (not portal/public users)
    users = env['res.users'].search([
        ('active', '=', True),
        ('share', '=', False),  # Internal users only
    ])

    _logger.info(f"AI Chat: Found {len(users)} internal users")

    # Create AI Assistant channel for each user
    session_model = env['ai.chat.session']
    created_count = 0

    for user in users:
        try:
            # Switch to user's context
            user_env = env(user=user.id)
            user_session_model = user_env['ai.chat.session']

            # Create AI channel for this user
            channel = user_session_model.get_or_create_ai_channel_for_user()

            if channel:
                created_count += 1
                _logger.info(f"AI Chat: Created AI Assistant channel for user {user.name} (ID: {user.id})")
        except Exception as e:
            _logger.error(f"AI Chat: Failed to create AI channel for user {user.name} (ID: {user.id}): {e}")

    _logger.info(f"AI Chat: Successfully created {created_count} AI Assistant channels")

    # Commit changes
    cr.commit()
