/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Global AI Chat Service
 * Provides global functions to access AI chat functionality
 */
const aiChatGlobalService = {
    start(env) {
        console.log("[AI Chat] Global service started");
        
        // Add global function to open main AI chat
        window.openAIChat = async function() {
            try {
                const rpc = env.services.rpc;
                const result = await rpc('/ai_chat/get_channel_id');
                
                if (result.success) {
                    window.location.href = `/web#action=mail.action_discuss&active_id=${result.channel_id}`;
                } else {
                    console.error('Failed to get AI channel:', result.error);
                    // Fallback to general discuss
                    window.location.href = '/web#action=mail.action_discuss';
                }
            } catch (error) {
                console.error('Error opening AI chat:', error);
                window.location.href = '/web#action=mail.action_discuss';
            }
        };
        
        // Add global function to create new AI chat
        window.createNewAIChat = async function(name = null) {
            try {
                const rpc = env.services.rpc;
                const result = await rpc('/ai_chat/create_new_channel', { name });
                
                if (result.success) {
                    window.location.href = result.redirect_url;
                } else {
                    console.error('Failed to create new AI channel:', result.error);
                    alert('Failed to create new AI channel: ' + result.error);
                }
            } catch (error) {
                console.error('Error creating new AI channel:', error);
                alert('Error creating new AI channel: ' + error.message);
            }
        };
        
        // Add global function to list AI chats
        window.listAIChats = async function() {
            try {
                const rpc = env.services.rpc;
                const result = await rpc('/ai_chat/get_user_channels');
                
                if (result.success) {
                    console.log('Your AI chat sessions:', result.channels);
                    return result.channels;
                } else {
                    console.error('Failed to get AI channels:', result.error);
                    return [];
                }
            } catch (error) {
                console.error('Error getting AI channels:', error);
                return [];
            }
        };
        
        console.log("[AI Chat] Global functions available:");
        console.log("  - window.openAIChat() - Open main AI chat");
        console.log("  - window.createNewAIChat(name?) - Create new AI chat session");
        console.log("  - window.listAIChats() - List all AI chat sessions");

        return {};
    }
};

// Register the service
registry.category("services").add("ai_chat_global", aiChatGlobalService);