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
     * Toggle AI Chat floating window
     */
    async openChat() {
        // Trigger toggle event to open/close the floating chat window
        this.aiChat.addEventListener((event, data) => {});  // Dummy listener to ensure service is initialized
        // Manually trigger the toggle event
        const listeners = this.aiChat._listeners || [];
        // Use a more direct approach - call a toggle method we'll add to the service
        if (this.aiChat.toggleWindow) {
            this.aiChat.toggleWindow();
        }
    }
}

AIChatSystrayItem.template = "odoo_ai_chat.SystrayItem";

export const systrayItem = {
    Component: AIChatSystrayItem,
};

registry.category("systray").add("AIChatSystrayItem", systrayItem, { sequence: 1 });
