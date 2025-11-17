/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Context Tracker Service
 * Tracks the current view/record context so the AI can understand user location
 */

const contextTrackerService = {
    dependencies: ["action"],

    start(env, { action }) {
        console.log("[AI Chat] Context tracker service started");

        // Store current context
        let currentContext = null;

        // Track context changes by monitoring the action service
        const originalDoAction = action.doAction;
        action.doAction = function(...args) {
            // Call original method
            const result = originalDoAction.apply(this, args);

            // Update context after action is performed
            setTimeout(() => {
                updateContext(action.currentController);
            }, 100);

            return result;
        };

        /**
         * Update the current context from the action controller
         */
        function updateContext(controller) {
            if (!controller) {
                return;
            }

            try {
                const actionData = controller.action;
                const props = controller.props;

                // Build context information
                const context = {
                    // Current model being viewed
                    model: actionData.res_model || props?.resModel,

                    // Action ID and name
                    action_id: actionData.id,
                    action_name: actionData.name || actionData.display_name,

                    // Current record(s) if viewing specific records
                    active_id: props?.resId || actionData.context?.active_id,
                    active_ids: actionData.context?.active_ids || (props?.resId ? [props.resId] : []),

                    // View type (form, list, kanban, etc.)
                    view_type: props?.type || actionData.view_mode,

                    // Domain filter currently applied
                    domain: actionData.domain,

                    // Full action context
                    context: actionData.context || {},

                    // Timestamp when context was captured
                    timestamp: Date.now(),
                };

                currentContext = context;

                console.log("[AI Chat] Context updated:", {
                    model: context.model,
                    active_id: context.active_id,
                    view_type: context.view_type,
                    action_name: context.action_name,
                });
            } catch (error) {
                console.debug("[AI Chat] Could not update context:", error);
            }
        }

        /**
         * Get the current context
         */
        function getCurrentContext() {
            // If we have a recent context (within last 30 seconds), use it
            if (currentContext && (Date.now() - currentContext.timestamp < 30000)) {
                return currentContext;
            }

            // Otherwise try to get fresh context from current controller
            if (action.currentController) {
                updateContext(action.currentController);
                return currentContext;
            }

            return null;
        }

        /**
         * Get context with record data
         * Fetches the actual record data for the current context
         */
        async function getContextWithRecordData(orm) {
            const context = getCurrentContext();

            if (!context || !context.model || !context.active_id) {
                return context;
            }

            try {
                // Read the current record to get its data
                const recordData = await orm.call(
                    context.model,
                    'read',
                    [[context.active_id]],
                    {
                        limit: 1,
                    }
                );

                if (recordData && recordData.length > 0) {
                    return {
                        ...context,
                        record_data: recordData[0],
                    };
                }
            } catch (error) {
                console.debug("[AI Chat] Could not fetch record data:", error);
            }

            return context;
        }

        // Initialize context from current controller
        if (action.currentController) {
            updateContext(action.currentController);
        }

        return {
            getCurrentContext,
            getContextWithRecordData,
        };
    },
};

registry.category("services").add("ai_chat_context_tracker", contextTrackerService);
