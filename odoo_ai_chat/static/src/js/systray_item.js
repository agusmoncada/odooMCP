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
        this.action = useService("action");
        this.messaging = useService("messaging");
        // Ensure typing indicator service starts (for Discuss AI chat)
        useService("ai_chat_typing_indicator");
    }

    /**
     * Open AI Chat in bottom chat window
     */
    async openChat() {
        try {
            console.log("[AI Chat] Opening AI chat...");

            // Get or create the AI channel
            const result = await this.rpc("/ai_chat/get_channel_id", {});
            console.log("[AI Chat] Channel result:", result);

            if (result.success && result.channel_id) {
                console.log("[AI Chat] Opening channel", result.channel_id);

                // Open the channel as a chat window at the bottom by setting its fold state
                await this.rpc("/web/dataset/call_kw/mail.channel/channel_fold", {
                    model: "mail.channel",
                    method: "channel_fold",
                    args: [[result.channel_id]],
                    kwargs: {
                        state: "open"
                    }
                });

                console.log("[AI Chat] Channel folded to open state");

                // Trigger a bus notification to refresh the messaging menu
                // This will make the chat window appear at the bottom
                try {
                    await this.messaging.isReady;
                    const messaging = await this.messaging.get();

                    // Force refresh of the messaging menu to show the chat window
                    if (messaging && messaging.refresh) {
                        await messaging.refresh();
                    }
                } catch (e) {
                    console.log("[AI Chat] Could not refresh messaging:", e.message);
                }
            }
        } catch (error) {
            console.error("[AI Chat] Error opening AI chat:", error);
            console.error("[AI Chat] Error stack:", error.stack);
        }
    }
}

AIChatSystrayItem.template = "odoo_ai_chat.SystrayItem";

export const systrayItem = {
    Component: AIChatSystrayItem,
};

registry.category("systray").add("AIChatSystrayItem", systrayItem, { sequence: 1 });
