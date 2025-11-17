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
                const currentContext = ai_chat_context_tracker.getCurrentContext();

                // Only update if context has changed and we have a valid context
                if (!currentContext || !currentContext.model || !currentContext.active_id) {
                    return;
                }

                // Check if context actually changed
                const contextKey = `${currentContext.model}-${currentContext.active_id}`;
                const lastContextKey = lastContext ? `${lastContext.model}-${lastContext.active_id}` : null;

                if (contextKey === lastContextKey) {
                    return;
                }

                lastContext = currentContext;

                console.log("[AI Chat] Updating AI channel context:", currentContext);

                // Find the AI channel for the current user
                // We'll call a backend method to update the context
                await rpc("/ai_chat/update_channel_context", {
                    context: currentContext,
                });

                console.log("[AI Chat] AI channel context updated successfully");
            } catch (error) {
                console.debug("[AI Chat] Could not update AI channel context:", error);
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
