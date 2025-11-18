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
        let lastValidContext = null;  // Keep track of last context with model + active_id

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

                // Debug: log controller structure to understand what we're working with
                console.log("[AI Chat] Debug controller:", {
                    controller: controller,
                    actionData: actionData,
                    props: props,
                    actionDataKeys: actionData ? Object.keys(actionData) : null,
                    propsKeys: props ? Object.keys(props) : null
                });

                // Build context information
                const context = {
                    // Current model being viewed
                    model: actionData?.res_model || props?.resModel,

                    // Action ID and name
                    action_id: actionData?.id,
                    action_name: actionData?.name || actionData?.display_name,

                    // Current record(s) if viewing specific records
                    active_id: props?.resId || actionData?.context?.active_id,
                    active_ids: actionData?.context?.active_ids || (props?.resId ? [props.resId] : []),

                    // View type (form, list, kanban, etc.)
                    view_type: props?.type || actionData?.view_mode,

                    // Domain filter currently applied
                    domain: actionData?.domain,

                    // Full action context
                    context: actionData?.context || {},

                    // Timestamp when context was captured
                    timestamp: Date.now(),
                };

                // If action-based context detection failed, try URL-based fallback
                if (!context.model || !context.active_id) {
                    const urlContext = getContextFromUrl();
                    if (urlContext.model && urlContext.active_id) {
                        console.log("[AI Chat] Using URL-based context fallback:", urlContext);
                        context.model = urlContext.model;
                        context.active_id = urlContext.active_id;
                        context.view_type = urlContext.view_type;
                    }
                }

                currentContext = context;

                // If this is a valid context (has model AND active_id), save it as lastValidContext
                // This makes the context "sticky" - it persists even when navigating to views
                // without a specific record (like Discuss, Apps list, etc.)
                if (context.model && context.active_id) {
                    lastValidContext = context;
                    console.log("[AI Chat] Context updated (VALID - saved as sticky):", {
                        model: context.model,
                        active_id: context.active_id,
                        view_type: context.view_type,
                        action_name: context.action_name,
                    });
                } else {
                    console.log("[AI Chat] Context updated (no model/active_id - keeping last valid):", {
                        model: context.model,
                        active_id: context.active_id,
                        view_type: context.view_type,
                        action_name: context.action_name,
                    });
                }
            } catch (error) {
                console.debug("[AI Chat] Could not update context:", error);
            }
        }

        /**
         * Get the current context
         * Returns the last valid context (with model + active_id) if available
         */
        function getCurrentContext() {
            // If we have a recent valid context (within last 5 minutes), use it
            // This makes context "sticky" across navigation
            if (lastValidContext && (Date.now() - lastValidContext.timestamp < 300000)) {
                return lastValidContext;
            }

            // Otherwise try to get fresh context from current controller
            if (action.currentController) {
                updateContext(action.currentController);
                if (lastValidContext) {
                    return lastValidContext;
                }
                return currentContext;
            }

            return lastValidContext || currentContext;
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

        /**
         * Extract context from URL as fallback when action-based detection fails
         * Parses URLs like /web#id=12&model=res.partner&view_type=form
         */
        function getContextFromUrl() {
            try {
                const url = window.location.href;
                const hash = window.location.hash;
                
                console.log("[AI Chat] Parsing URL for context:", url);
                
                // Parse URL hash parameters
                const params = new URLSearchParams(hash.replace('#', ''));
                
                // Look for various patterns
                let model = params.get('model');
                let active_id = params.get('id');
                let view_type = params.get('view_type');
                
                // Alternative patterns
                if (!model) {
                    // Check if URL contains action parameter with embedded model info
                    const actionMatch = hash.match(/action=(\d+)/);
                    const idMatch = hash.match(/id=(\d+)/);
                    const modelMatch = hash.match(/model=([^&]+)/);
                    
                    if (modelMatch) model = modelMatch[1];
                    if (idMatch) active_id = parseInt(idMatch[1]);
                }
                
                // Special cases for common models
                if (hash.includes('res.partner') || url.includes('/contacts/')) {
                    model = 'res.partner';
                }
                if (hash.includes('account.move') || url.includes('/invoices/')) {
                    model = 'account.move';
                }
                if (hash.includes('project.project') || url.includes('/projects/')) {
                    model = 'project.project';
                }
                
                return {
                    model: model,
                    active_id: active_id ? parseInt(active_id) : null,
                    view_type: view_type || 'form'
                };
            } catch (error) {
                console.debug("[AI Chat] Error parsing URL:", error);
                return {};
            }
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
