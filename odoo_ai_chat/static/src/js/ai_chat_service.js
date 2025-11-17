/** @odoo-module **/

import { registry } from "@web/core/registry";
import { jsonrpc } from "@web/core/network/rpc_service";

/**
 * AI Chat Service
 * Manages communication with the AI chat backend
 */
export const aiChatService = {
    dependencies: ["rpc"],

    start(env, { rpc }) {
        let currentSessionId = null;
        let sessions = [];
        let messages = [];
        let listeners = [];

        /**
         * Send a message to the AI
         */
        async function sendMessage(message, sessionId = null, viewContext = null) {
            try {
                const result = await rpc("/ai_chat/send_message", {
                    session_id: sessionId || currentSessionId,
                    message: message,
                    view_context: viewContext,
                });

                if (result.success) {
                    currentSessionId = result.session_id;

                    // Add messages to local cache
                    messages.push({
                        role: "user",
                        content: message,
                        create_date: new Date().toISOString(),
                    });

                    messages.push({
                        id: result.message_id,
                        role: "assistant",
                        content: result.message,
                        create_date: new Date().toISOString(),
                        tool_calls: result.tool_calls,
                        graph_data: result.graph_data,
                    });

                    notifyListeners('message', result);
                    return result;
                }

                throw new Error(result.error || "Unknown error");
            } catch (error) {
                console.error("Error sending message:", error);
                throw error;
            }
        }

        /**
         * Get list of sessions
         */
        async function getSessions() {
            try {
                const result = await rpc("/ai_chat/get_sessions", {});
                if (result.success) {
                    sessions = result.sessions;
                    notifyListeners('sessions', sessions);
                    return sessions;
                }
                throw new Error(result.error || "Unknown error");
            } catch (error) {
                console.error("Error getting sessions:", error);
                throw error;
            }
        }

        /**
         * Get messages for a session
         */
        async function getMessages(sessionId) {
            try {
                const result = await rpc("/ai_chat/get_messages", {
                    session_id: sessionId,
                });

                if (result.success) {
                    messages = result.messages;
                    currentSessionId = result.session_id;
                    notifyListeners('messages', messages);
                    return messages;
                }

                throw new Error(result.error || "Unknown error");
            } catch (error) {
                console.error("Error getting messages:", error);
                throw error;
            }
        }

        /**
         * Create a new session
         */
        async function newSession(name = "New Chat") {
            try {
                const result = await rpc("/ai_chat/new_session", {
                    name: name,
                });

                if (result.success) {
                    currentSessionId = result.session_id;
                    messages = [];
                    await getSessions();
                    notifyListeners('new_session', result);
                    return result;
                }

                throw new Error(result.error || "Unknown error");
            } catch (error) {
                console.error("Error creating new session:", error);
                throw error;
            }
        }

        /**
         * Delete a session
         */
        async function deleteSession(sessionId) {
            try {
                const result = await rpc("/ai_chat/delete_session", {
                    session_id: sessionId,
                });

                if (result.success) {
                    if (currentSessionId === sessionId) {
                        currentSessionId = null;
                        messages = [];
                    }
                    await getSessions();
                    notifyListeners('delete_session', sessionId);
                    return result;
                }

                throw new Error(result.error || "Unknown error");
            } catch (error) {
                console.error("Error deleting session:", error);
                throw error;
            }
        }

        /**
         * Add event listener
         */
        function addEventListener(callback) {
            listeners.push(callback);
            return () => {
                listeners = listeners.filter(l => l !== callback);
            };
        }

        /**
         * Notify all listeners
         */
        function notifyListeners(event, data) {
            listeners.forEach(callback => {
                try {
                    callback(event, data);
                } catch (error) {
                    console.error("Error in listener:", error);
                }
            });
        }

        /**
         * Get current session ID
         */
        function getCurrentSessionId() {
            return currentSessionId;
        }

        /**
         * Set current session ID
         */
        function setCurrentSessionId(sessionId) {
            currentSessionId = sessionId;
        }

        /**
         * Get current messages
         */
        function getCurrentMessages() {
            return messages;
        }

        /**
         * Toggle floating chat window
         */
        function toggleWindow() {
            notifyListeners('toggle_window', {});
        }

        return {
            sendMessage,
            getSessions,
            getMessages,
            newSession,
            deleteSession,
            addEventListener,
            getCurrentSessionId,
            setCurrentSessionId,
            getCurrentMessages,
            toggleWindow,
        };
    },
};

registry.category("services").add("ai_chat", aiChatService);
