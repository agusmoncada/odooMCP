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
    }

    /**
     * Open AI Chat Widget
     */
    async openChat() {
        // Open the AI chat in fullscreen mode (no header/footer)
        this.action.doAction({
            type: "ir.actions.client",
            tag: "ai_chat_widget",
            name: "AI Chat Assistant",
            target: "fullscreen",
        });
    }
}

AIChatSystrayItem.template = "odoo_ai_chat.SystrayItem";

export const systrayItem = {
    Component: AIChatSystrayItem,
};

registry.category("systray").add("AIChatSystrayItem", systrayItem, { sequence: 1 });
