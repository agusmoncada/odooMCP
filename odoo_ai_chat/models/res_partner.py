"""Extension for res.partner to keep AI bot online"""

from odoo import api, models


class ResPartner(models.Model):
    """Extend res.partner to keep AI Assistant Bot always online"""

    _inherit = 'res.partner'

    @api.depends('user_ids.im_status')
    def _compute_im_status(self):
        """Override IM status computation to keep AI bot always online"""
        # Call super for all partners
        super()._compute_im_status()

        # Find AI bot and set it to online
        for partner in self:
            if partner.email == 'ai.assistant@odoo.local':
                partner.im_status = 'online'
