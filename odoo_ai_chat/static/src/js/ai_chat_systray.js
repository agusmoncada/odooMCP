/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, useRef } from "@odoo/owl";

/**
 * AI Chat Systray Widget
 * Provides quick access to AI chat functionality from the systray
 */
export class AIChatSystray extends Component {
    static template = "odoo_ai_chat.AIChatSystray";
    static props = [];
    
    // Add fallback template if the main one is not available
    static getFallbackTemplate() {
        return `
            <div class="ai-chat-systray-fallback">
                <button class="btn btn-sm btn-outline-primary" title="AI Chat" onclick="window.location='/web#action=mail.action_discuss'">
                    <i class="fa fa-robot"></i> AI
                </button>
            </div>
        `;
    }

    setup() {
        this.state = useState({
            showDropdown: false,
            channels: [],
            loading: false
        });
        
        this.rpc = this.env.services.rpc;
        this.dropdownRef = useRef("dropdown");
    }

    async toggleDropdown() {
        this.state.showDropdown = !this.state.showDropdown;
        
        if (this.state.showDropdown && this.state.channels.length === 0) {
            await this.loadChannels();
        }
    }

    async loadChannels() {
        this.state.loading = true;
        try {
            const result = await this.rpc('/ai_chat/get_user_channels');
            if (result.success) {
                this.state.channels = result.channels.slice(0, 5); // Show only first 5
            }
        } catch (error) {
            console.error('Error loading AI channels:', error);
        } finally {
            this.state.loading = false;
        }
    }

    async createNewChat() {
        try {
            const result = await this.rpc('/ai_chat/create_new_channel');
            
            if (result.success) {
                window.location.href = result.redirect_url;
            } else {
                this.env.services.notification.add(
                    'Failed to create new AI channel: ' + result.error, 
                    { type: 'danger' }
                );
            }
        } catch (error) {
            console.error('Error creating new AI channel:', error);
            this.env.services.notification.add(
                'Error creating new AI channel', 
                { type: 'danger' }
            );
        }
        this.state.showDropdown = false;
    }

    openChannel(channelId) {
        const url = `/web#action=mail.action_discuss&active_id=${channelId}`;
        window.location.href = url;
        this.state.showDropdown = false;
    }

    openMainChat() {
        // Open the main AI assistant channel (first or create new)
        this.rpc('/ai_chat/get_channel_id').then(result => {
            if (result.success) {
                window.location.href = `/web#action=mail.action_discuss&active_id=${result.channel_id}`;
            }
        });
        this.state.showDropdown = false;
    }
}

// Register in systray with template checking and error handling
function registerSystrayComponent() {
    try {
        // Check if the template exists before registering
        const templateRegistry = registry.category("main_components");
        
        // Register a simpler fallback if templates aren't available
        const SimpleFallbackComponent = class extends Component {
            static template = "AIChatSystrayFallback";
            static props = [];
            
            async openMainAIChat() {
                try {
                    const response = await fetch('/ai_chat/get_channel_id', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        credentials: 'include'
                    });
                    const result = await response.json();
                    
                    if (result.success) {
                        window.location.href = `/web#action=mail.action_discuss&active_id=${result.channel_id}`;
                    } else {
                        // Fallback to general discuss
                        window.location.href = '/web#action=mail.action_discuss';
                    }
                } catch (error) {
                    console.error('Error opening AI chat:', error);
                    window.location.href = '/web#action=mail.action_discuss';
                }
            }
        };
        
        // Register simple fallback template
        const fallbackTemplate = `
            <button class="btn position-relative" t-on-click="openMainAIChat" title="AI Chat">
                <i class="fa fa-robot text-primary" style="font-size: 16px;"/>
            </button>
        `;
        
        // Try to register the fallback template first
        try {
            const templateCategory = registry.category("templates");
            if (templateCategory) {
                templateCategory.add("AIChatSystrayFallback", fallbackTemplate);
            }
        } catch (e) {
            console.debug("[AI Chat] Could not register fallback template:", e);
        }
        
        // Register the systray component
        registry.category("systray").add("AIChatSystray", {
            Component: SimpleFallbackComponent,
        }, { sequence: 50 }); // Lower priority to avoid conflicts
        
        console.log("[AI Chat] Simple systray component registered successfully");
        
    } catch (error) {
        console.warn("[AI Chat] Could not register systray component:", error);
        
        // Ultimate fallback - add a global function
        window.openAIChat = function() {
            fetch('/ai_chat/get_channel_id', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include'
            }).then(r => r.json()).then(result => {
                if (result.success) {
                    window.location.href = `/web#action=mail.action_discuss&active_id=${result.channel_id}`;
                } else {
                    window.location.href = '/web#action=mail.action_discuss';
                }
            }).catch(() => {
                window.location.href = '/web#action=mail.action_discuss';
            });
        };
        console.log("[AI Chat] Global function window.openAIChat() is available");
    }
}

// Register when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', registerSystrayComponent);
} else {
    registerSystrayComponent();
}