/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";

/**
 * AI Chat Manager Component
 * Allows users to create and manage multiple AI chat sessions in Discuss
 */
export class AIChatManager extends Component {
    static template = "odoo_ai_chat.AIChatManager";
    
    setup() {
        this.state = useState({
            channels: [],
            loading: false,
            showManager: false
        });
        
        this.rpc = this.env.services.rpc;
    }

    async toggleManager() {
        this.state.showManager = !this.state.showManager;
        
        if (this.state.showManager && this.state.channels.length === 0) {
            await this.loadChannels();
        }
    }

    async loadChannels() {
        this.state.loading = true;
        try {
            const result = await this.rpc('/ai_chat/get_user_channels');
            if (result.success) {
                this.state.channels = result.channels;
            } else {
                console.error('Failed to load AI channels:', result.error);
            }
        } catch (error) {
            console.error('Error loading AI channels:', error);
        } finally {
            this.state.loading = false;
        }
    }

    async createNewChannel() {
        const name = prompt('Enter a name for the new AI chat session (optional):');
        
        try {
            const result = await this.rpc('/ai_chat/create_new_channel', { 
                name: name || undefined 
            });
            
            if (result.success) {
                // Redirect to the new channel in Discuss
                window.location.href = result.redirect_url;
            } else {
                alert('Failed to create new AI channel: ' + result.error);
            }
        } catch (error) {
            console.error('Error creating new AI channel:', error);
            alert('Error creating new AI channel: ' + error.message);
        }
    }

    openChannel(channelId) {
        const url = `/web#action=mail.action_discuss&active_id=${channelId}`;
        window.location.href = url;
    }
}

// Register the component as a service so it can be used globally
const aiChatManagerService = {
    start(env) {
        console.log("[AI Chat] AI Chat Manager service started");
        
        // Add global method to create new AI chat
        window.createNewAIChat = async function() {
            try {
                const rpc = env.services.rpc;
                const result = await rpc('/ai_chat/create_new_channel');
                
                if (result.success) {
                    window.location.href = result.redirect_url;
                } else {
                    alert('Failed to create new AI channel: ' + result.error);
                }
            } catch (error) {
                console.error('Error creating new AI channel:', error);
                alert('Error creating new AI channel: ' + error.message);
            }
        };

        return {};
    }
};

registry.category("services").add("ai_chat_manager", aiChatManagerService);