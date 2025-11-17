/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Typing Indicator System for Discuss
 * Listens for typing_status bus notifications
 */

const typingIndicatorService = {
    dependencies: ["bus_service"],

    start(env, { bus_service }) {
        console.log("[AI Chat] Typing indicator service started");

        // Track typing status per channel
        const typingStatus = new Map();

        // Listen for ALL bus notifications
        bus_service.addEventListener("notification", ({ detail: notifications }) => {
            // Validate that notifications is iterable
            if (!notifications || typeof notifications[Symbol.iterator] !== 'function') {
                console.warn("[AI Chat] Invalid notifications format:", notifications);
                return;
            }

            for (const notification of notifications) {
                // Validate notification is an array before destructuring
                if (!Array.isArray(notification) || notification.length < 2) {
                    console.warn("[AI Chat] Invalid notification format:", notification);
                    continue;
                }

                const [channel, message] = notification;

                console.log("[AI Chat] Bus notification received:", {
                    channel,
                    message,
                    type: typeof message,
                });

                // Handle typing_status notifications
                if (channel && channel.toString().includes('mail.channel')) {
                    // Check if message has typing status
                    if (message && typeof message === 'object') {
                        // Log the full message structure
                        console.log("[AI Chat] Channel notification payload:", JSON.stringify(message, null, 2));

                        // Handle different notification formats
                        const payload = message.payload || message;

                        if (payload.is_typing !== undefined) {
                            const channelId = payload.channel_id;
                            const partnerId = payload.partner_id;
                            const isTyping = payload.is_typing;

                            console.log(`[AI Chat] Typing status: Partner ${partnerId} ${isTyping ? 'started' : 'stopped'} typing in channel ${channelId}`);

                            // Update typing status
                            if (isTyping) {
                                typingStatus.set(channelId, { partnerId, timestamp: Date.now() });

                                // Show typing indicator in the UI
                                showTypingIndicator(channelId, partnerId);

                                // Auto-clear after 10 seconds
                                setTimeout(() => {
                                    if (typingStatus.get(channelId)?.timestamp === typingStatus.get(channelId)?.timestamp) {
                                        typingStatus.delete(channelId);
                                        hideTypingIndicator(channelId);
                                    }
                                }, 10000);
                            } else {
                                typingStatus.delete(channelId);
                                hideTypingIndicator(channelId);
                            }
                        }
                    }
                }

                // Also check for the specific notification type
                if (channel === 'mail.channel.partner/typing_status') {
                    console.log("[AI Chat] Typing notification received:", message);
                }
            }
        });

        /**
         * Show typing indicator in the Discuss UI
         */
        function showTypingIndicator(channelId, partnerId) {
            // Find the message list container for this channel
            const messageList = document.querySelector('.o_mail_thread');

            if (messageList) {
                // Remove any existing typing indicator
                const existingIndicator = messageList.querySelector('.o_ai_typing_indicator');
                if (existingIndicator) {
                    existingIndicator.remove();
                }

                // Create typing indicator element
                const indicator = document.createElement('div');
                indicator.className = 'o_ai_typing_indicator o_mail_message';
                indicator.style.cssText = 'padding: 10px; margin: 10px 0; display: flex; align-items: center;';
                indicator.setAttribute('data-channel-id', channelId);

                indicator.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <div style="display: flex; gap: 4px;">
                            <span style="width: 8px; height: 8px; border-radius: 50%; background: #875a7b; animation: typing-bounce 1.4s infinite;"></span>
                            <span style="width: 8px; height: 8px; border-radius: 50%; background: #875a7b; animation: typing-bounce 1.4s infinite 0.2s;"></span>
                            <span style="width: 8px; height: 8px; border-radius: 50%; background: #875a7b; animation: typing-bounce 1.4s infinite 0.4s;"></span>
                        </div>
                        <span style="color: #6c757d; font-size: 14px; font-style: italic;">AI is thinking...</span>
                    </div>
                `;

                // Add CSS animation if not already present
                if (!document.getElementById('ai-typing-animation')) {
                    const style = document.createElement('style');
                    style.id = 'ai-typing-animation';
                    style.textContent = `
                        @keyframes typing-bounce {
                            0%, 60%, 100% {
                                transform: translateY(0);
                                opacity: 0.4;
                            }
                            30% {
                                transform: translateY(-10px);
                                opacity: 1;
                            }
                        }
                    `;
                    document.head.appendChild(style);
                }

                // Append to message list
                messageList.appendChild(indicator);

                // Scroll to bottom
                messageList.scrollTop = messageList.scrollHeight;

                console.log("[AI Chat] Typing indicator shown in Discuss");
            } else {
                console.log("[AI Chat] Could not find message list to show typing indicator");
            }
        }

        /**
         * Hide typing indicator
         */
        function hideTypingIndicator(channelId) {
            const indicator = document.querySelector(`.o_ai_typing_indicator[data-channel-id="${channelId}"]`);
            if (indicator) {
                indicator.remove();
                console.log("[AI Chat] Typing indicator hidden");
            }
        }

        return {
            getTypingStatus: (channelId) => typingStatus.get(channelId),
        };
    },
};

registry.category("services").add("ai_chat_typing_indicator", typingIndicatorService);
