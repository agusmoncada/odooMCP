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
        this.notification = useService("notification");
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

                // Wait for messaging to be ready
                await this.messaging.isReady;
                const messaging = await this.messaging.get();
                console.log("[AI Chat] Messaging service ready");

                // Get or create the thread
                let thread;
                try {
                    thread = messaging.models['Thread'].findFromIdentifyingData({
                        id: result.channel_id,
                        model: 'mail.channel',
                    });

                    if (!thread) {
                        console.log("[AI Chat] Creating new thread");
                        thread = messaging.models['Thread'].insert({
                            id: result.channel_id,
                            model: 'mail.channel',
                        });
                    }
                } catch (e) {
                    console.error("[AI Chat] Error getting/creating thread:", e);
                    // Fallback: just set fold state and reload
                    await this.rpc("/web/dataset/call_kw/mail.channel/channel_fold", {
                        model: "mail.channel",
                        method: "channel_fold",
                        args: [[result.channel_id]],
                        kwargs: { state: "open" }
                    });
                    this.notification.add("AI Chat will open after page refresh", { type: "info" });
                    setTimeout(() => window.location.reload(), 1000);
                    return;
                }

                console.log("[AI Chat] Thread:", thread);
                console.log("[AI Chat] Thread methods:", Object.keys(thread));

                // Open the chat window using the thread
                if (thread && thread.openAsChatWindow) {
                    console.log("[AI Chat] Calling thread.openAsChatWindow()");
                    thread.openAsChatWindow();
                } else if (thread && thread.open) {
                    console.log("[AI Chat] Calling thread.open()");
                    thread.open();
                } else {
                    console.log("[AI Chat] No open method found on thread");
                    // Set fold state and reload
                    await this.rpc("/web/dataset/call_kw/mail.channel/channel_fold", {
                        model: "mail.channel",
                        method: "channel_fold",
                        args: [[result.channel_id]],
                        kwargs: { state: "open" }
                    });
                    this.notification.add("AI Chat will open after page refresh", { type: "info" });
                    setTimeout(() => window.location.reload(), 1000);
                }
            }
        } catch (error) {
            console.error("[AI Chat] Error opening AI chat:", error);
            console.error("[AI Chat] Error stack:", error.stack);
            this.notification.add("Error opening AI Chat. Please try again.", { type: "danger" });
        }
    }
}

AIChatSystrayItem.template = "odoo_ai_chat.SystrayItem";

export const systrayItem = {
    Component: AIChatSystrayItem,
};

registry.category("systray").add("AIChatSystrayItem", systrayItem, { sequence: 1 });
