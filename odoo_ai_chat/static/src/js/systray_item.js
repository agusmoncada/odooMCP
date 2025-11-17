/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * AI Chat Systray Item
 * Displays AI icon in the system tray
 */
export class AIChatSystrayItem extends Component {
    setup() {
        this.aiChat = useService("ai_chat");
        this.action = useService("action");
        // Ensure typing indicator service starts (for Discuss AI chat)
        useService("ai_chat_typing_indicator");
    }

    /**
     * Open AI Chat in Discuss
     */
    async openChat() {
        // Redirect to controller that opens or creates the AI Assistant channel in Discuss
        window.location.href = '/ai_chat/open_discuss_channel';
    }
}

AIChatSystrayItem.template = "odoo_ai_chat.SystrayItem";

export const systrayItem = {
    Component: AIChatSystrayItem,
};

registry.category("systray").add("AIChatSystrayItem", systrayItem, { sequence: 1 });
