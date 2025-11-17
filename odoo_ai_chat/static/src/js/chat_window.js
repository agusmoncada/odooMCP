/** @odoo-module **/

import { Component, useState, useRef, onMounted, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ChartRenderer } from "./chart_renderer";

/**
 * Floating AI Chat Window
 * Displays AI chat as a floating window at the bottom right of the screen
 */
export class FloatingChatWindow extends Component {
    setup() {
        this.aiChat = useService("ai_chat");
        this.notification = useService("notification");
        this.action = useService("action");

        this.state = useState({
            isOpen: false,
            isMinimized: false,
            messages: [],
            sessions: [],
            currentSessionId: null,
            inputMessage: "",
            loading: false,
            showSessions: false,
            uploadingFile: false,
        });

        this.messagesEndRef = useRef("messagesEnd");
        this.fileInputRef = useRef("fileInput");
        this.charts = {};  // Store chart instances

        // Listen for chat events
        onMounted(async () => {
            // Listen for toggle events from systray
            this.removeListener = this.aiChat.addEventListener((event, data) => {
                if (event === "toggle_window") {
                    this.toggleWindow();
                } else if (event === "message") {
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

        // Render charts after patching
        onPatched(() => {
            if (this.state.isOpen && !this.state.isMinimized) {
                this.renderCharts();
            }
        });
    }

    willUnmount() {
        if (this.removeListener) {
            this.removeListener();
        }
        // Destroy all charts
        Object.values(this.charts).forEach(chart => {
            if (chart && chart.destroy) {
                chart.destroy();
            }
        });
    }

    /**
     * Toggle chat window visibility
     */
    async toggleWindow() {
        this.state.isOpen = !this.state.isOpen;

        if (this.state.isOpen) {
            this.state.isMinimized = false;
            await this.loadSessions();
        }
    }

    /**
     * Minimize/maximize window
     */
    toggleMinimize() {
        this.state.isMinimized = !this.state.isMinimized;
    }

    /**
     * Close window
     */
    closeWindow() {
        this.state.isOpen = false;
        this.state.isMinimized = false;
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

            // Destroy existing charts before loading new session
            Object.values(this.charts).forEach(chartRenderer => {
                if (chartRenderer && chartRenderer.destroy) {
                    chartRenderer.destroy();
                }
            });
            this.charts = {};

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
     * Get current view context
     */
    getCurrentContext() {
        try {
            const currentController = this.action.currentController;

            if (!currentController) {
                return null;
            }

            const action = currentController.action;
            const props = currentController.props;

            return {
                model: action.res_model || props.resModel,
                action_id: action.id,
                action_name: action.name || action.display_name,
                active_id: action.context?.active_id,
                active_ids: action.context?.active_ids || [],
                view_type: props.type || action.view_mode,
                domain: action.domain,
                context: action.context || {},
            };
        } catch (error) {
            console.debug("Could not get current view context:", error);
            return null;
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

            // Get current view context
            const viewContext = this.getCurrentContext();

            // Send to backend
            const result = await this.aiChat.sendMessage(
                message,
                this.state.currentSessionId,
                viewContext
            );

            if (result.success) {
                this.state.currentSessionId = result.session_id;
                this.scrollToBottom();
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
            // Destroy existing charts before creating new session
            Object.values(this.charts).forEach(chartRenderer => {
                if (chartRenderer && chartRenderer.destroy) {
                    chartRenderer.destroy();
                }
            });
            this.charts = {};

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

    /**
     * Handle file attachment button click
     */
    onAttachFile() {
        if (this.fileInputRef.el) {
            this.fileInputRef.el.click();
        }
    }

    /**
     * Handle file selection
     */
    async onFileSelected(event) {
        const file = event.target.files[0];
        if (!file) return;

        if (file.type !== 'application/pdf') {
            this.notification.add("Please select a PDF file", {
                type: "warning",
            });
            event.target.value = '';
            return;
        }

        // Check file size (max 10MB)
        if (file.size > 10 * 1024 * 1024) {
            this.notification.add("File size exceeds 10MB limit", {
                type: "warning",
            });
            event.target.value = '';
            return;
        }

        try {
            this.state.uploadingFile = true;

            // Upload file
            const formData = new FormData();
            formData.append('file', file);
            formData.append('session_id', this.state.currentSessionId || '');

            const response = await fetch('/ai_chat/upload_pdf', {
                method: 'POST',
                body: formData,
            });

            const result = await response.json();

            if (result.success) {
                this.notification.add(`PDF processed successfully: ${result.filename}`, {
                    type: "success",
                });

                // Add a message about the uploaded file
                this.state.inputMessage = `I've uploaded an invoice PDF "${result.filename}". Please analyze it and create a vendor bill.`;
                await this.sendMessage();
            } else {
                this.notification.add(result.error || "Failed to process PDF", {
                    type: "danger",
                });
            }
        } catch (error) {
            console.error("Error uploading PDF:", error);
            this.notification.add("Failed to upload PDF file", {
                type: "danger",
            });
        } finally {
            this.state.uploadingFile = false;
            event.target.value = '';  // Reset input
        }
    }

    /**
     * Render all charts in messages
     */
    renderCharts() {
        setTimeout(() => {
            this.state.messages.forEach((message, index) => {
                if (message.graph_data && message.graph_data.type) {
                    const canvasId = `chart_${message.id || index}`;
                    const canvas = document.getElementById(canvasId);

                    if (canvas && !this.charts[canvasId]) {
                        const renderer = new ChartRenderer(canvas, message.graph_data);
                        const chart = renderer.render();
                        if (chart) {
                            this.charts[canvasId] = renderer;
                        }
                    }
                }
            });
        }, 50);
    }
}

FloatingChatWindow.template = "odoo_ai_chat.FloatingChatWindow";

// Register as a main component that's always mounted
export const floatingChatWindowService = {
    dependencies: [],
    start() {
        // This component will be mounted via the webclient
        return {};
    },
};

registry.category("main_components").add("FloatingChatWindow", {
    Component: FloatingChatWindow,
});
