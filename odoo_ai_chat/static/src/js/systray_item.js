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
        this.rpc = useService("rpc");
        this.messaging = useService("messaging");
        // Ensure typing indicator service starts (for Discuss AI chat)
        useService("ai_chat_typing_indicator");
    }

    /**
     * Open AI Chat in bottom chat window
     */
    async openChat() {
        try {
            // Get or create the AI channel
            const result = await this.rpc("/ai_chat/get_channel_id", {});

            if (result.success && result.channel_id) {
                // Wait for messaging to be ready
                await this.messaging.isReady;

                // Get the thread (channel) from the messaging store
                const messaging = this.messaging.get();
                const thread = messaging.store.Thread.insert({
                    id: result.channel_id,
                    model: 'mail.channel',
                });

                // Open the chat window at the bottom
                thread.open();
            }
        } catch (error) {
            console.error("Error opening AI chat:", error);
        }
    }
}

AIChatSystrayItem.template = "odoo_ai_chat.SystrayItem";

export const systrayItem = {
    Component: AIChatSystrayItem,
};

registry.category("systray").add("AIChatSystrayItem", systrayItem, { sequence: 1 });
