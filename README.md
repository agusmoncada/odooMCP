# Odoo AI Chat Assistant

An advanced AI-powered chat assistant addon for Odoo v16 Community Edition that integrates MCP (Model Context Protocol) server capabilities with OpenRouter AI provider. Now with **graph generation** and **PDF invoice processing**!

**✨ NEW: Lightweight, zero-dependency version! No pip install needed!**

## Features

- **AI Chat Interface**: Clean, modern chat interface accessible from anywhere in Odoo via the systray icon (🤖 emoji)
- **MCP Server Integration**: Built-in MCP server that exposes Odoo data and operations to the AI
- **OpenRouter Integration**: Connect to multiple AI models through OpenRouter (GPT-4, Claude, LLaMA, etc.)
- **Dynamic Model Dropdown**: Fetch and select from all available OpenRouter models
- **Tool Calling**: AI can interact with Odoo data using MCP tools (search, read, create, update records)
- **📊 Graph Generation**: AI can create interactive charts and graphs from Odoo data (line, bar, pie, area, scatter, doughnut)
- **📄 PDF Invoice Processing**: Upload PDF invoices and automatically create vendor bills with AI-powered data extraction
- **Session Management**: Create multiple chat sessions and switch between them
- **Chat History**: All conversations are saved and can be reviewed later
- **Configurable**: Extensive configuration options for AI behavior, model selection, and more
- **🚀 Zero Dependencies**: Uses lightweight alternatives - no pip install required!

## Installation

### ✅ SIMPLE Installation - No Dependencies!

**This addon now uses lightweight, pure Python alternatives that are already in Odoo v16!**

### 1. Prerequisites

- Odoo v16 Community Edition
- Python 3.8+ (comes with Odoo)
- That's it! No external packages needed!

### 2. Install the Module

**No pip install required!** The addon uses:
- **PyPDF2** (already in Odoo v16) instead of pdfplumber
- **Pure Python** (stdlib) instead of pandas/numpy
- **Odoo's built-in tools** instead of Pillow

```bash
# 1. Copy the addon to your Odoo addons directory
cp -r odoo_ai_chat /path/to/odoo/addons/

# 2. Restart Odoo
sudo systemctl restart odoo
# or
./odoo-bin -c /path/to/odoo.conf

# 3. Update the Apps list in Odoo
# Go to Apps > Update Apps List

# 4. Search for "AI Chat Assistant" and click Install
```

1. Visit [OpenRouter](https://openrouter.ai/)
2. Create an account
3. Go to [Keys](https://openrouter.ai/keys) and generate an API key

### 4. Configure in Odoo

1. Go to **Settings > General Settings**
2. Scroll down to the **AI Chat** section
3. Enter your OpenRouter API key
4. Click **🔄 Refresh Models** to fetch all available AI models
5. Select your preferred AI model from the dropdown
6. Configure other settings:
   - **Temperature**: Control randomness (0-2, default 0.7)
   - **Max Tokens**: Maximum response length (default 2000)
   - **Enable MCP Tools**: Allow AI to interact with Odoo data (recommended)
   - **System Prompt**: Customize the AI's behavior and personality
7. Click **Save**

### 🚨 Troubleshooting

**Issue:** "PyPDF2 not available" error
- **Cause:** PyPDF2 might not be included in your Odoo installation
- **Fix:** `pip3 install PyPDF2>=1.26.0`

**Issue:** Chat window doesn't open
- **Solution:** Clear browser cache and refresh (Ctrl+F5)

**Issue:** No robot icon in menu bar
- **Solution:**
  1. Check that the module is installed (Apps > AI Chat Assistant)
  2. Refresh the page
  3. Check browser console for JavaScript errors

**Issue:** PDF processing fails
- **Cause:** PDF might be image-based (scanned) without text
- **Solution:** Use OCR-enabled PDFs or text-based PDFs

**Issue:** Graph generation fails
- **Solution:** Check that the model has numeric fields for the y-axis

For more details, see `DEPENDENCY_ISSUES.md` in the repository.

## Usage

### Starting a Chat

1. Click the **robot icon** in the top menu bar
2. A chat window will open
3. Type your message and press Enter or click the send button
4. The AI will respond to your queries

### Managing Sessions

- **New Chat**: Click the "New Chat" button to start a fresh conversation
- **View Sessions**: Click the hamburger menu icon to see all your chat sessions
- **Switch Sessions**: Click on any session to load its conversation history
- **Delete Sessions**: Click the trash icon next to a session to delete it

### AI Capabilities

When MCP tools are enabled, the AI can:

- **Search Records**: Find data across any Odoo model
- **Read Records**: Get detailed information about specific records
- **Create Records**: Create new records (with appropriate permissions)
- **Update Records**: Modify existing records (with appropriate permissions)
- **Get Model Info**: Learn about model structures and fields
- **📊 Generate Graphs**: Create interactive charts from your data
- **📄 Process PDF Invoices**: Extract data and create vendor bills automatically

### Example Queries

**General queries:**
```
"Show me the latest 5 customers"
"What are the open sales orders?"
"Create a new contact named John Doe with email john@example.com"
"What fields are available in the res.partner model?"
"Find all invoices from last month"
```

**Graph generation:**
```
"Show me a bar chart of sales by month for the last quarter"
"Create a pie chart of revenue by customer"
"Generate a line graph showing order trends over the past year"
"Show me total sales by salesperson in a bar chart"
```

**PDF invoice processing:**
1. Click the paperclip icon (📎) in the chat input
2. Select a PDF invoice file
3. The AI will automatically:
   - Extract invoice data (vendor, amounts, line items)
   - Show you the extracted information
   - Create a vendor bill in Odoo
   - Attach the PDF to the bill

Or simply say: "I uploaded an invoice, please process it and create a vendor bill"

## MCP Server Features

The integrated MCP server provides the following tools to the AI:

### Available Tools

1. **search_records**: Search for records in any Odoo model
   - Parameters: model, domain, fields, limit

6. **generate_graph**: Create charts and graphs from Odoo data
   - Parameters: graph_type, model, y_field, x_field, group_by, aggregation, date_range, title
   - Supports: line, bar, pie, area, scatter, doughnut charts
   - Aggregations: sum, avg, count, min, max

7. **create_vendor_bill_from_pdf**: Create vendor bill from parsed PDF invoice data
   - Parameters: invoice_data, pdf_content_b64, filename
   - Automatically matches or creates vendors and products

2. **read_record**: Read a specific record
   - Parameters: model, record_id, fields

3. **create_record**: Create a new record
   - Parameters: model, values

4. **write_record**: Update an existing record
   - Parameters: model, record_id, values

5. **get_model_fields**: Get field information for a model
   - Parameters: model

## Available AI Models

OpenRouter supports many AI models. Popular choices:

- **OpenAI**: `openai/gpt-4`, `openai/gpt-3.5-turbo`
- **Anthropic**: `anthropic/claude-3-opus`, `anthropic/claude-3-sonnet`
- **Meta**: `meta-llama/llama-3-70b`, `meta-llama/llama-3-8b`
- **Google**: `google/gemini-pro`
- **Mistral**: `mistralai/mistral-medium`

See [OpenRouter Models](https://openrouter.ai/models) for a complete list.

## Security & Permissions

- All chat sessions are user-specific (users can only see their own chats)
- MCP tool operations respect Odoo's access rights and record rules
- API keys are stored securely in Odoo's configuration parameters
- All AI interactions are logged for audit purposes

## Architecture

### Backend Components

- **Models**:
  - `ai.chat.session`: Chat session management
  - `ai.chat.message`: Individual messages
  - `mcp.server.registry`: MCP server registry
  - `res.config.settings`: Configuration

- **Controllers**:
  - `/ai_chat/send_message`: Send message to AI
  - `/ai_chat/get_sessions`: Get user's sessions
  - `/ai_chat/get_messages`: Get session messages
  - `/ai_chat/new_session`: Create new session
  - `/ai_chat/delete_session`: Delete session

- **Services**:
  - `OpenRouterProvider`: AI provider integration
  - `MCPServer`: MCP server implementation

### Frontend Components

- **JavaScript Services**:
  - `ai_chat`: Main chat service

- **Components**:
  - `AIChatSystrayItem`: Systray icon
  - `AIChatWidget`: Main chat interface

## Troubleshooting

### Common Issues

1. **"OpenRouter API key not configured"**
   - Make sure you've saved the API key in Settings > AI Chat

2. **"AI service error"**
   - Check your API key is valid
   - Ensure you have credits on your OpenRouter account
   - Verify your internet connection

3. **Tool calls not working**
   - Enable "MCP Tools" in settings
   - Check user has proper access rights for the requested operations

4. **Chat not appearing**
   - Clear your browser cache
   - Refresh the page
   - Check JavaScript console for errors

## Development

### Directory Structure

```
odoo_ai_chat/
├── __init__.py
├── __manifest__.py
├── controllers/
│   ├── __init__.py
│   └── main.py
├── models/
│   ├── __init__.py
│   ├── ai_chat_message.py
│   ├── ai_chat_session.py
│   ├── ai_provider.py
│   ├── mcp_server.py
│   └── res_config_settings.py
├── security/
│   └── ir.model.access.csv
├── views/
│   ├── ai_chat_views.xml
│   └── res_config_settings_views.xml
└── static/
    └── src/
        ├── css/
        │   └── ai_chat.css
        ├── js/
        │   ├── ai_chat_service.js
        │   ├── ai_chat_widget.js
        │   └── systray_item.js
        └── xml/
            └── ai_chat_templates.xml
```

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## License

LGPL-3

## Support

For issues and questions, please contact your system administrator or the module maintainer.

## Credits

- Built for Odoo v16 Community Edition
- Powered by [OpenRouter](https://openrouter.ai/)
- Uses Model Context Protocol (MCP) for tool integration
