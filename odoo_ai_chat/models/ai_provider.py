"""OpenRouter AI Provider Integration"""

import json
import logging
import requests
from typing import Dict, List, Optional, Any

from odoo import api, exceptions

_logger = logging.getLogger(__name__)


class OpenRouterProvider:
    """
    OpenRouter AI Provider for handling AI chat requests.

    OpenRouter provides access to multiple AI models through a unified API.
    """

    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "openai/gpt-3.5-turbo", site_url: str = "", site_name: str = "Odoo AI Chat"):
        """
        Initialize OpenRouter provider

        Args:
            api_key: OpenRouter API key
            model: Model to use (default: openai/gpt-3.5-turbo)
            site_url: Your site URL for OpenRouter attribution
            site_name: Your site name for OpenRouter attribution
        """
        self.api_key = api_key
        self.model = model
        self.site_url = site_url
        self.site_name = site_name

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto"
    ) -> Dict[str, Any]:
        """
        Send chat request to OpenRouter

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            tools: Optional list of tools/functions for the AI to use
            tool_choice: How to handle tools ("auto", "none", or specific tool)

        Returns:
            Response dict with AI message and metadata
        """
        if not self.api_key:
            raise exceptions.UserError("OpenRouter API key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        try:
            response = requests.post(
                self.API_URL,
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            _logger.error(f"OpenRouter API request failed: {str(e)}")
            if hasattr(e.response, 'text'):
                _logger.error(f"Response: {e.response.text}")
            raise exceptions.UserError(f"AI service error: {str(e)}")

    def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        mcp_tools: List[Dict],
        max_iterations: int = 3
    ) -> Dict[str, Any]:
        """
        Chat with MCP tool support, handling multiple tool calls

        Args:
            messages: Chat messages
            mcp_tools: Available MCP tools
            max_iterations: Maximum tool call iterations

        Returns:
            Final response with tool call results
        """
        # Convert MCP tools to OpenAI function format
        tools = self._convert_mcp_tools_to_openai(mcp_tools)

        current_messages = messages.copy()
        iteration = 0

        while iteration < max_iterations:
            response = self.chat(
                messages=current_messages,
                tools=tools,
                tool_choice="auto"
            )

            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            finish_reason = choice.get("finish_reason")

            # Add assistant message to history
            current_messages.append(message)

            # Check if AI wants to call tools
            tool_calls = message.get("tool_calls", [])

            if not tool_calls or finish_reason == "stop":
                # No more tool calls, return final response
                return {
                    "success": True,
                    "message": message.get("content", ""),
                    "tool_calls": [],
                    "iterations": iteration + 1
                }

            # Process tool calls
            tool_results = []
            for tool_call in tool_calls:
                tool_name = tool_call.get("function", {}).get("name")
                tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                tool_id = tool_call.get("id")

                try:
                    tool_args = json.loads(tool_args_str)
                    tool_results.append({
                        "tool_call_id": tool_id,
                        "name": tool_name,
                        "arguments": tool_args
                    })
                except json.JSONDecodeError:
                    _logger.error(f"Failed to parse tool arguments: {tool_args_str}")

            # Return with tool calls for external processing
            return {
                "success": True,
                "message": message.get("content"),
                "tool_calls": tool_results,
                "iterations": iteration + 1,
                "requires_tool_execution": True,
                "messages": current_messages
            }

        # Max iterations reached
        return {
            "success": False,
            "error": "Maximum tool call iterations reached",
            "iterations": iteration
        }

    def _convert_mcp_tools_to_openai(self, mcp_tools: List[Dict]) -> List[Dict]:
        """Convert MCP tool format to OpenAI function format"""
        openai_tools = []

        for tool in mcp_tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool.get("inputSchema", {})
                }
            }
            openai_tools.append(openai_tool)

        return openai_tools

    def get_available_models(self) -> List[Dict[str, str]]:
        """Get list of available models from OpenRouter"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
            }
            response = requests.get(
                "https://openrouter.ai/api/v1/models",
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            models_data = response.json()
            return models_data.get("data", [])
        except Exception as e:
            _logger.error(f"Failed to fetch available models: {str(e)}")
            return []
