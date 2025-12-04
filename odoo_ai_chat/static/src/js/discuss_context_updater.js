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
                // Only log detailed info for forced updates to reduce spam
                if (forceUpdate) {
                    console.log("[AI Chat] updateAiChannelContext called, forceUpdate:", forceUpdate);
                }
                
                const currentContext = ai_chat_context_tracker.getCurrentContext();

                // Only log detailed context for forced updates or when context changes significantly
                if (forceUpdate && currentContext) {
                    console.log("[AI Chat] Current context from tracker:", currentContext);
                    console.log("[AI Chat] Context details:", {
                        model: currentContext.model,
                        active_id: currentContext.active_id,
                        view_type: currentContext.view_type,
                        action_name: currentContext.action_name,
                        timestamp: currentContext.timestamp
                    });
                }

                // Only update if context has changed and we have a valid context
                if (!currentContext) {
                    // Only log if this is a forced update to reduce spam
                    if (forceUpdate) {
                        console.log("[AI Chat] No current context, skipping update");
                    }
                    return;
                }

                if (!currentContext.model) {
                    // Only log if this is a forced update to reduce spam
                    if (forceUpdate) {
                        console.log("[AI Chat] Context missing model, skipping update");
                    }
                    return;
                }

                if (!currentContext.active_id) {
                    // Only log if this is a forced update to reduce spam
                    if (forceUpdate) {
                        console.log("[AI Chat] Context missing active_id, skipping update");
                    }
                    return;
                }

                // Check if context actually changed
                const contextKey = `${currentContext.model}-${currentContext.active_id}`;
                const lastContextKey = lastContext ? `${lastContext.model}-${lastContext.active_id}` : null;

                // Only log context comparison for forced updates
                if (forceUpdate) {
                    console.log("[AI Chat] Context keys - current:", contextKey, "last:", lastContextKey);
                }

                if (!forceUpdate && contextKey === lastContextKey) {
                    // Don't log this every time to reduce spam
                    return;
                }

                lastContext = currentContext;

                console.log("[AI Chat] Updating AI channel context:", currentContext);

                // Prepare context for backend - ensure it's serializable
                const contextForBackend = {
                    model: currentContext.model,
                    active_id: currentContext.active_id,
                    active_ids: currentContext.active_ids || [],
                    action_id: currentContext.action_id,
                    action_name: currentContext.action_name,
                    view_type: currentContext.view_type,
                    timestamp: currentContext.timestamp || Date.now()
                };

                console.log("[AI Chat] Context prepared for backend:", contextForBackend);

                // Find the AI channel for the current user
                // We'll call a backend method to update the context
                console.log("[AI Chat] About to call RPC with context:", contextForBackend);
                console.log("[AI Chat] RPC parameters being sent:", {
                    context: contextForBackend,
                });
                
                let result;
                try {
                    // In Odoo 16, the rpc service expects params to be passed directly
                    // The 'context' key conflicts with Odoo's built-in context
                    // Use 'view_context' instead to avoid conflicts
                    const rpcParams = {
                        view_context: contextForBackend,
                    };

                    console.log("[AI Chat] Calling RPC with params:", JSON.stringify(rpcParams, null, 2));
                    console.log("[AI Chat] contextForBackend type:", typeof contextForBackend);
                    console.log("[AI Chat] contextForBackend.model:", contextForBackend?.model);
                    console.log("[AI Chat] contextForBackend.active_id:", contextForBackend?.active_id);

                    result = await rpc("/ai_chat/update_channel_context", rpcParams);

                    console.log("[AI Chat] RPC call successful, result:", result);

                    if (result.success) {
                        console.log("[AI Chat] AI channel context updated successfully");
                    } else {
                        console.error("[AI Chat] Failed to update context:", result.error);
                    }
                } catch (error) {
                    console.error("[AI Chat] RPC call failed:", error);
                    console.error("[AI Chat] RPC error details:", error.message, error.stack);
                    // Log but don't throw to avoid breaking other functionality
                }
            } catch (error) {
                console.error("[AI Chat] Could not update AI channel context:", error);
                // Don't let context errors break other functionality
                return;
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

        // Check periodically but less aggressively, and skip if in Discuss without a record
        setInterval(() => {
            const currentContext = ai_chat_context_tracker.getCurrentContext();
            // Skip periodic updates if we're in Discuss interface without a specific record
            if (currentContext && currentContext.action_name === "Discuss" && (!currentContext.model || !currentContext.active_id)) {
                // Don't spam updates when just browsing Discuss
                console.log("[AI Chat] Skipping periodic update - in Discuss without specific record");
                return;
            }
            // Also skip if no context at all to avoid spam
            if (!currentContext || !currentContext.model) {
                console.log("[AI Chat] Skipping periodic update - no valid context");
                return;
            }
            scheduleContextUpdate(false);
        }, 15000);  // Further reduced frequency to 15s

        // Initial update - force it to ensure first context is sent
        scheduleContextUpdate(true);

        return {
            updateContext: updateAiChannelContext,
        };
    },
};

registry.category("services").add("ai_chat_discuss_context_updater", discussContextUpdaterService);
