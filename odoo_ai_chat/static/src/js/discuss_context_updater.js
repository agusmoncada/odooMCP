/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Discuss Context Updater Service
 * Monitors view changes and updates the AI channel's context
 */

const discussContextUpdaterService = {
    dependencies: ["ai_chat_context_tracker", "orm", "rpc"],

    start(env, { ai_chat_context_tracker, orm, rpc }) {
        console.log("[AI Chat] Discuss context updater service started");

        let lastContext = null;
        let updateTimer = null;

        /**
         * Update the AI channel's context when the view changes
         */
        async function updateAiChannelContext() {
            try {
                console.log("[AI Chat] updateAiChannelContext called");
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

                if (contextKey === lastContextKey) {
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
         */
        function scheduleContextUpdate() {
            if (updateTimer) {
                clearTimeout(updateTimer);
            }

            // Wait 500ms before updating to avoid too many updates
            updateTimer = setTimeout(() => {
                updateAiChannelContext();
            }, 500);
        }

        // Listen for action changes
        // We'll use a MutationObserver to detect when the URL changes
        const observer = new MutationObserver(() => {
            scheduleContextUpdate();
        });

        // Observe the document body for changes
        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });

        // Also check periodically (every 3 seconds) to catch any missed updates
        setInterval(() => {
            scheduleContextUpdate();
        }, 3000);

        // Initial update
        scheduleContextUpdate();

        return {
            updateContext: updateAiChannelContext,
        };
    },
};

registry.category("services").add("ai_chat_discuss_context_updater", discussContextUpdaterService);
