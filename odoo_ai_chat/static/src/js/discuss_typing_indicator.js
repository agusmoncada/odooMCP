/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Typing Indicator System for Discuss
 * Listens for typing_status bus notifications
 */

const typingIndicatorService = {
    dependencies: ["bus_service"],

    start(env, { bus_service }) {
        console.log("[AI Chat] Typing indicator service started - Version 3");

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
                // Odoo 16 notification format: {type: "...", payload: {...}}
                if (!notification || typeof notification !== 'object') {
                    continue;
                }

                const notificationType = notification.type;
                const payload = notification.payload;

                console.log("[AI Chat] Bus notification received:", {
                    type: notificationType,
                    payload: payload,
                });

                // Handle typing_status notifications - cast a wide net for different formats
                if (notificationType && (
                    notificationType.includes('typing_status') ||
                    notificationType.includes('typing') ||
                    (payload && (payload.is_typing !== undefined || payload.isTyping !== undefined))
                )) {

                    console.log("[AI Chat] Typing notification detected:", {
                        type: notificationType,
                        payload: payload
                    });

                    if (payload) {
                        // Extract typing info from payload - try multiple formats
                        const channelId = payload.channel_id || payload.channel?.id || payload.id;
                        const partnerId = payload.partner_id || payload.persona?.partner?.id || payload.member_id;
                        const isTyping = payload.is_typing ?? payload.isTyping ?? payload.typing;

                        if (channelId !== undefined && isTyping !== undefined) {
                            console.log(`[AI Chat] Typing status: Partner ${partnerId} ${isTyping ? 'started' : 'stopped'} typing in channel ${channelId}`);

                            // Update typing status
                            if (isTyping) {
                                typingStatus.set(channelId, { partnerId, timestamp: Date.now() });

                                // Show typing indicator in the UI
                                showTypingIndicator(channelId, partnerId);

                                // Auto-clear after 10 seconds
                                setTimeout(() => {
                                    const current = typingStatus.get(channelId);
                                    if (current && current.timestamp === typingStatus.get(channelId)?.timestamp) {
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
            }
        });

        /**
         * Show typing indicator in the Discuss UI (NOT in Chatter)
         */
        function showTypingIndicator(channelId, partnerId) {
            // Try multiple selectors for different Discuss views and Odoo versions
            const possibleSelectors = [
                '.o_mail_thread',                    // Classic selector
                '.o-mail-Thread',                    // New component-based selector
                '.o_MessageList',                    // Alternative selector
                '.o_Composer_messageList',           // Composer area
                '.o-mail-Message-list',              // Hyphenated version
                '[data-thread-local-id]',            // Thread container
                '.o-mail-Thread-messageList',        // Specific thread message list
                '.o_mail_thread_content'             // Content area
            ];
            
            let messageList = null;
            let selectorUsed = null;
            
            for (const selector of possibleSelectors) {
                messageList = document.querySelector(selector);
                if (messageList) {
                    selectorUsed = selector;
                    console.log(`[AI Chat] Found message list using selector: ${selector}`);
                    break;
                }
            }
            
            if (!messageList) {
                console.log("[AI Chat] Could not find any message list container. Available elements:", {
                    mailElements: Array.from(document.querySelectorAll('[class*="mail"], [class*="Mail"]'))
                        .map(el => `${el.tagName}.${el.className}`).slice(0, 5),
                    messageElements: Array.from(document.querySelectorAll('[class*="Message"], [class*="message"]'))
                        .map(el => `${el.tagName}.${el.className}`).slice(0, 5),
                    threadElements: Array.from(document.querySelectorAll('[class*="Thread"], [class*="thread"]'))
                        .map(el => `${el.tagName}.${el.className}`).slice(0, 5),
                    discussElements: Array.from(document.querySelectorAll('[class*="discuss"], [class*="Discuss"]'))
                        .map(el => `${el.tagName}.${el.className}`).slice(0, 5),
                    allDataAttributes: Array.from(document.querySelectorAll('[data-thread], [data-channel], [data-message]'))
                        .map(el => `${el.tagName}[${Array.from(el.attributes).filter(attr => attr.name.startsWith('data-')).map(attr => attr.name).join(', ')}]`).slice(0, 5)
                });
                
                // Try one more desperate attempt with any element that looks like a message container
                const desperateSelectors = [
                    '[role="log"]',                    // ARIA role for chat logs
                    '.o_content',                      // Generic content area
                    '[data-o-mail-thread]',           // Odoo mail thread attribute
                    '.o_action_manager_content',       // Action manager content
                    '.o_mail_discuss'                  // Generic discuss class
                ];
                
                for (const selector of desperateSelectors) {
                    const fallbackElement = document.querySelector(selector);
                    if (fallbackElement) {
                        console.log(`[AI Chat] Found fallback container: ${selector}`);
                        messageList = fallbackElement;
                        selectorUsed = selector + ' (fallback)';
                        break;
                    }
                }
                
                if (!messageList) {
                    return;
                }
            }

            // Check if we're in Chatter (form view) vs Discuss (messaging app)
            // Don't show typing indicator in Chatter - only in Discuss
            const isInChatter = messageList.closest('.o-mail-Chatter') ||
                               messageList.closest('.o_Message_threadPane') ||
                               messageList.closest('.o_form_view');
            
            // Also check if we're in the Discuss app by looking at URL or app context
            const isInDiscuss = window.location.href.includes('/web#action') && 
                              (window.location.href.includes('discuss') || 
                               document.querySelector('[data-menu-xmlid*="discuss"]') ||
                               document.querySelector('.o_mail_discuss_sidebar') ||
                               document.querySelector('.o-mail-MessagingMenu'));

            console.log("[AI Chat] Context check:", {
                isInChatter,
                isInDiscuss,
                url: window.location.href,
                hasDiscussElements: !!document.querySelector('.o_mail_discuss_sidebar')
            });

            if (isInChatter && !isInDiscuss) {
                console.log("[AI Chat] Skipping typing indicator - in Chatter, not Discuss");
                return;
            }

            // Remove any existing typing indicator
            const existingIndicator = messageList.querySelector('.o_ai_typing_indicator');
            if (existingIndicator) {
                existingIndicator.remove();
            }

            // Create typing indicator element
            const indicator = document.createElement('div');
            indicator.className = 'o_ai_typing_indicator o_mail_message';
            indicator.style.cssText = `
                padding: 10px; 
                margin: 10px 0; 
                display: flex; 
                align-items: center;
                background-color: rgba(135, 90, 123, 0.05);
                border-radius: 8px;
                border-left: 4px solid #875a7b;
            `;
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

            // Try different insertion strategies based on the container type
            try {
                if (selectorUsed === '.o_mail_thread' || selectorUsed === '.o_mail_thread_content') {
                    // Classic append for older versions
                    messageList.appendChild(indicator);
                } else {
                    // For newer component-based layouts, try to find the message container
                    const messageContainer = messageList.querySelector('.o-mail-Message-list') || 
                                           messageList.querySelector('[class*="message"]') || 
                                           messageList;
                    messageContainer.appendChild(indicator);
                }

                // Scroll to bottom if the container is scrollable
                if (messageList.scrollHeight > messageList.clientHeight) {
                    messageList.scrollTop = messageList.scrollHeight;
                }

                console.log(`[AI Chat] Typing indicator shown in Discuss using ${selectorUsed}`);
            } catch (error) {
                console.error("[AI Chat] Failed to insert typing indicator:", error);
                // Fallback: try simple append
                try {
                    messageList.appendChild(indicator);
                    console.log("[AI Chat] Typing indicator shown using fallback method");
                } catch (fallbackError) {
                    console.error("[AI Chat] Fallback insertion also failed:", fallbackError);
                }
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

        // Add a global test function for debugging
        window.testAITypingIndicator = function(channelId = 1, showFor = 3000) {
            console.log(`[AI Chat] Testing typing indicator for channel ${channelId}...`);
            showTypingIndicator(channelId, 'test-partner');
            
            setTimeout(() => {
                hideTypingIndicator(channelId);
                console.log(`[AI Chat] Test typing indicator hidden after ${showFor}ms`);
            }, showFor);
        };

        return {
            getTypingStatus: (channelId) => typingStatus.get(channelId),
            testTypingIndicator: window.testAITypingIndicator,
        };
    },
};

registry.category("services").add("ai_chat_typing_indicator", typingIndicatorService);
