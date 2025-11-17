/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Discuss Context Updater Service
 * Monitors view changes and updates the AI channel's context
 */

const discussContextUpdaterService = {
    dependencies: ["ai_chat_context_tracker", "orm", "rpc", "bus_service"],

    start(env, { ai_chat_context_tracker, orm, rpc, bus_service }) {
        console.log("[AI Chat] Discuss context updater service started");

        let lastContext = null;
        let updateTimer = null;
        let currentAiChannelId = null;

        /**
         * Update the AI channel's context when the view changes
         */
        async function updateAiChannelContext(forceUpdate = false) {
            try {
                console.log("[AI Chat] updateAiChannelContext called, forceUpdate:", forceUpdate);
                const currentContext = ai_chat_context_tracker.getCurrentContext();

                console.log("[AI Chat] Current context from tracker:", currentContext);

                // Only update if context has changed and we have a valid context
                if (!currentContext) {
                    console.log("[AI Chat] No current context, skipping update");
                    return;
                }

                if (!currentContext.model) {
                    console.log("[AI Chat] Context missing model, skipping update");
                    return;
                }

                if (!currentContext.active_id) {
                    console.log("[AI Chat] Context missing active_id, skipping update");
                    return;
                }

                // Check if context actually changed
                const contextKey = `${currentContext.model}-${currentContext.active_id}`;
                const lastContextKey = lastContext ? `${lastContext.model}-${lastContext.active_id}` : null;

                console.log("[AI Chat] Context keys - current:", contextKey, "last:", lastContextKey);

                if (!forceUpdate && contextKey === lastContextKey) {
                    console.log("[AI Chat] Context unchanged, skipping update");
                    return;
                }

                lastContext = currentContext;

                console.log("[AI Chat] Updating AI channel context:", currentContext);

                // Find the AI channel for the current user
                // We'll call a backend method to update the context
                const result = await rpc("/ai_chat/update_channel_context", {
                    context: currentContext,
                });

                console.log("[AI Chat] Update result:", result);

                if (result.success) {
                    console.log("[AI Chat] AI channel context updated successfully");
                } else {
                    console.error("[AI Chat] Failed to update context:", result.error);
                }
            } catch (error) {
                console.error("[AI Chat] Could not update AI channel context:", error);
            }
        }

        /**
         * Schedule a context update (debounced)
         * If forceUpdate is true, call immediately without debouncing
         */
        function scheduleContextUpdate(forceUpdate = false) {
            // If forcing update, call immediately without debouncing
            if (forceUpdate) {
                if (updateTimer) {
                    clearTimeout(updateTimer);
                    updateTimer = null;
                }
                updateAiChannelContext(true);
                return;
            }

            // Otherwise debounce as usual
            if (updateTimer) {
                clearTimeout(updateTimer);
            }

            // Wait 500ms before updating to avoid too many updates
            updateTimer = setTimeout(() => {
                updateAiChannelContext(false);
            }, 500);
        }

        // Listen for when AI channel is opened/created
        // When a new AI chat is opened, force send the current context
        bus_service.addEventListener("notification", ({ detail: notifications }) => {
            for (const notif of notifications) {
                // Check if this is a channel-related notification
                if (notif.type === "mail.channel/joined" ||
                    notif.type === "mail.channel/new_message" ||
                    notif.type === "mail.channel/last_interest_dt_changed") {
                    const channelId = notif.payload?.id || notif.payload?.channel_id;

                    // If the AI channel ID changed, force update the context
                    if (channelId && channelId !== currentAiChannelId) {
                        console.log("[AI Chat] AI channel changed from", currentAiChannelId, "to", channelId, "- forcing context update");
                        currentAiChannelId = channelId;
                        // Force send context for new channel
                        scheduleContextUpdate(true);
                    }
                }
            }
        });

        // Listen for action changes
        // We'll use a MutationObserver to detect when the URL changes
        const observer = new MutationObserver(() => {
            scheduleContextUpdate(false);
        });

        // Observe the document body for changes
        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });

        // Also check periodically (every 3 seconds) to catch any missed updates
        setInterval(() => {
            scheduleContextUpdate(false);
        }, 3000);

        // Initial update - force it to ensure first context is sent
        scheduleContextUpdate(true);

        return {
            updateContext: updateAiChannelContext,
        };
    },
};

registry.category("services").add("ai_chat_discuss_context_updater", discussContextUpdaterService);
