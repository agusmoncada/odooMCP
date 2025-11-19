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

// Register in systray with error handling
try {
    registry.category("systray").add("AIChatSystray", {
        Component: AIChatSystray,
    }, { sequence: 10 });
    console.log("[AI Chat] Systray component registered successfully");
} catch (error) {
    console.warn("[AI Chat] Could not register systray component:", error);
}