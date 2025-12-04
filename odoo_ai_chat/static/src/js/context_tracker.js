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
                console.log("[AI Chat] updateContext called with null controller");
                return;
            }

            try {
                const actionData = controller.action;
                const props = controller.props;

                // Debug: log controller structure to understand what we're working with
                console.log("[AI Chat] Debug controller:", {
                    controllerKeys: controller ? Object.keys(controller) : null,
                    actionData: actionData,
                    props: props,
                    actionDataKeys: actionData ? Object.keys(actionData) : null,
                    propsKeys: props ? Object.keys(props) : null
                });

                // Try to extract model and active_id from multiple sources
                let model = null;
                let active_id = null;
                let action_name = null;
                let view_type = null;

                // Source 1: action data
                if (actionData) {
                    model = actionData.res_model;
                    action_name = actionData.name || actionData.display_name;
                    active_id = actionData.context?.active_id || actionData.res_id;
                    view_type = actionData.view_mode;
                    console.log("[AI Chat] From actionData:", {model, active_id, action_name, view_type});
                }

                // Source 2: props
                if (props) {
                    if (!model && props.resModel) model = props.resModel;
                    if (!active_id && props.resId) active_id = props.resId;
                    if (!view_type && props.type) view_type = props.type;
                    console.log("[AI Chat] After props:", {model, active_id, view_type});
                }

                // Source 3: Try to access component state if available (Odoo 16 OWL)
                if (controller.component) {
                    const component = controller.component;
                    if (component.props) {
                        if (!model && component.props.resModel) model = component.props.resModel;
                        if (!active_id && component.props.resId) active_id = component.props.resId;
                        console.log("[AI Chat] From component.props:", {model, active_id});
                    }
                    // Try to access state
                    if (component.state) {
                        if (!active_id && component.state.resId) active_id = component.state.resId;
                        console.log("[AI Chat] From component.state:", {active_id});
                    }
                }

                // Build context information
                const context = {
                    // Current model being viewed
                    model: model,

                    // Action ID and name
                    action_id: actionData?.id,
                    action_name: action_name,

                    // Current record(s) if viewing specific records
                    active_id: active_id,
                    active_ids: actionData?.context?.active_ids || (active_id ? [active_id] : []),

                    // View type (form, list, kanban, etc.)
                    view_type: view_type,

                    // Domain filter currently applied
                    domain: actionData?.domain,

                    // Full action context
                    context: actionData?.context || {},

                    // Timestamp when context was captured
                    timestamp: Date.now(),
                };

                console.log("[AI Chat] Context before URL fallback:", context);

                // If action-based context detection failed, try URL-based fallback
                if (!context.model || !context.active_id) {
                    const urlContext = getContextFromUrl();
                    if (urlContext.model) {
                        if (!context.model) context.model = urlContext.model;
                    }
                    if (urlContext.active_id) {
                        if (!context.active_id) context.active_id = urlContext.active_id;
                    }
                    if (urlContext.view_type && !context.view_type) {
                        context.view_type = urlContext.view_type;
                    }
                    console.log("[AI Chat] Context after URL fallback:", context);
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
         * Also handles Odoo 16 format: /web#id=8&cids=1&menu_id=114&action=102&model=res.partner&view_type=form
         */
        function getContextFromUrl() {
            try {
                const url = window.location.href;
                const hash = window.location.hash || '';

                console.log("[AI Chat] Parsing URL for context:", url);
                console.log("[AI Chat] URL hash:", hash);

                let model = null;
                let active_id = null;
                let view_type = null;

                // Method 1: Parse hash as URL params (remove leading #)
                if (hash.length > 1) {
                    const hashContent = hash.substring(1);  // Remove #
                    const params = new URLSearchParams(hashContent);

                    model = params.get('model');
                    active_id = params.get('id');
                    view_type = params.get('view_type');

                    console.log("[AI Chat] URLSearchParams result:", {model, active_id, view_type});
                }

                // Method 2: Regex fallback for model
                if (!model) {
                    const modelMatch = hash.match(/model=([^&]+)/);
                    if (modelMatch) {
                        model = decodeURIComponent(modelMatch[1]);
                        console.log("[AI Chat] Model from regex:", model);
                    }
                }

                // Method 3: Regex fallback for id
                if (!active_id) {
                    const idMatch = hash.match(/[&?#]id=(\d+)/);
                    if (idMatch) {
                        active_id = parseInt(idMatch[1]);
                        console.log("[AI Chat] ID from regex:", active_id);
                    }
                }

                // Method 4: Check for common URL patterns
                if (!model) {
                    if (hash.includes('res.partner') || url.includes('/contacts/')) {
                        model = 'res.partner';
                    } else if (hash.includes('sale.order') || url.includes('/sales/')) {
                        model = 'sale.order';
                    } else if (hash.includes('account.move') || url.includes('/invoices/')) {
                        model = 'account.move';
                    } else if (hash.includes('project.project') || url.includes('/projects/')) {
                        model = 'project.project';
                    } else if (hash.includes('crm.lead') || url.includes('/leads/')) {
                        model = 'crm.lead';
                    } else if (hash.includes('purchase.order')) {
                        model = 'purchase.order';
                    } else if (hash.includes('stock.picking')) {
                        model = 'stock.picking';
                    } else if (hash.includes('product.template') || hash.includes('product.product')) {
                        model = hash.includes('product.template') ? 'product.template' : 'product.product';
                    }

                    if (model) {
                        console.log("[AI Chat] Model from common patterns:", model);
                    }
                }

                const result = {
                    model: model,
                    active_id: active_id ? parseInt(active_id) : null,
                    view_type: view_type || (active_id ? 'form' : 'list')
                };

                console.log("[AI Chat] Final URL context:", result);

                return result;
            } catch (error) {
                console.error("[AI Chat] Error parsing URL:", error);
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
