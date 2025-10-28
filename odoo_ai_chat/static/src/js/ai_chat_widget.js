/** @odoo-module **/

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * AI Chat Widget
 * Main chat interface component
 */
export class AIChatWidget extends Component {
    setup() {
        this.aiChat = useService("ai_chat");
        this.notification = useService("notification");

        this.state = useState({
            messages: [],
            sessions: [],
            currentSessionId: null,
            inputMessage: "",
            loading: false,
            showSessions: false,
        });

        this.messagesEndRef = useRef("messagesEnd");

        // Load sessions on mount
        onMounted(async () => {
            await this.loadSessions();

            // Listen for chat events
            this.removeListener = this.aiChat.addEventListener((event, data) => {
                if (event === "message") {
                    this.state.messages = this.aiChat.getCurrentMessages();
                    this.scrollToBottom();
                } else if (event === "sessions") {
                    this.state.sessions = data;
                } else if (event === "messages") {
                    this.state.messages = data;
                    this.scrollToBottom();
                }
            });
        });
    }

    willUnmount() {
        if (this.removeListener) {
            this.removeListener();
        }
    }

    /**
     * Load sessions list
     */
    async loadSessions() {
        try {
            const sessions = await this.aiChat.getSessions();
            this.state.sessions = sessions;
        } catch (error) {
            this.notification.add("Failed to load chat sessions", {
                type: "danger",
            });
        }
    }

    /**
     * Load messages for a session
     */
    async loadSession(sessionId) {
        try {
            this.state.loading = true;
            const messages = await this.aiChat.getMessages(sessionId);
            this.state.messages = messages;
            this.state.currentSessionId = sessionId;
            this.state.showSessions = false;
            this.scrollToBottom();
        } catch (error) {
            this.notification.add("Failed to load chat messages", {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Send a message
     */
    async sendMessage() {
        const message = this.state.inputMessage.trim();
        if (!message) return;

        try {
            this.state.loading = true;
            this.state.inputMessage = "";

            // Optimistically add user message
            this.state.messages.push({
                role: "user",
                content: message,
                create_date: new Date().toISOString(),
            });
            this.scrollToBottom();

            // Send to backend
            const result = await this.aiChat.sendMessage(
                message,
                this.state.currentSessionId
            );

            if (result.success) {
                this.state.currentSessionId = result.session_id;
                await this.loadSessions();
            } else {
                this.notification.add(result.error || "Failed to send message", {
                    type: "danger",
                });
            }
        } catch (error) {
            this.notification.add("Failed to send message", {
                type: "danger",
            });
            console.error(error);
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Create new chat session
     */
    async newChat() {
        try {
            await this.aiChat.newSession();
            this.state.messages = [];
            this.state.currentSessionId = this.aiChat.getCurrentSessionId();
            this.state.showSessions = false;
        } catch (error) {
            this.notification.add("Failed to create new chat", {
                type: "danger",
            });
        }
    }

    /**
     * Delete a session
     */
    async deleteSession(sessionId, event) {
        event.stopPropagation();

        if (!confirm("Are you sure you want to delete this chat?")) {
            return;
        }

        try {
            await this.aiChat.deleteSession(sessionId);
            if (this.state.currentSessionId === sessionId) {
                this.state.messages = [];
                this.state.currentSessionId = null;
            }
        } catch (error) {
            this.notification.add("Failed to delete chat", {
                type: "danger",
            });
        }
    }

    /**
     * Toggle sessions sidebar
     */
    toggleSessions() {
        this.state.showSessions = !this.state.showSessions;
    }

    /**
     * Handle input key press
     */
    onInputKeyPress(event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            this.sendMessage();
        }
    }

    /**
     * Update input message
     */
    onInputChange(event) {
        this.state.inputMessage = event.target.value;
    }

    /**
     * Scroll to bottom of messages
     */
    scrollToBottom() {
        setTimeout(() => {
            if (this.messagesEndRef.el) {
                this.messagesEndRef.el.scrollIntoView({ behavior: "smooth" });
            }
        }, 100);
    }

    /**
     * Format date
     */
    formatDate(dateStr) {
        if (!dateStr) return "";
        const date = new Date(dateStr);
        const now = new Date();
        const diff = now - date;
        const days = Math.floor(diff / (1000 * 60 * 60 * 24));

        if (days === 0) {
            return date.toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
            });
        } else if (days === 1) {
            return "Yesterday";
        } else if (days < 7) {
            return `${days} days ago`;
        } else {
            return date.toLocaleDateString();
        }
    }
}

AIChatWidget.template = "odoo_ai_chat.ChatWidget";

registry.category("actions").add("ai_chat_widget", AIChatWidget);
