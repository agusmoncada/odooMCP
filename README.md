# Odoo AI Chat Assistant

An advanced AI-powered chat assistant addon for Odoo v16 Community Edition that integrates MCP (Model Context Protocol) server capabilities with OpenRouter AI provider. Now with **graph generation** and **PDF invoice processing**!

## Features

- **AI Chat Interface**: Clean, modern chat interface accessible from anywhere in Odoo via the systray icon
- **MCP Server Integration**: Built-in MCP server that exposes Odoo data and operations to the AI
- **OpenRouter Integration**: Connect to multiple AI models through OpenRouter (GPT-4, Claude, LLaMA, etc.)
- **Tool Calling**: AI can interact with Odoo data using MCP tools (search, read, create, update records)
- **📊 Graph Generation**: AI can create interactive charts and graphs from Odoo data (line, bar, pie, area, scatter, doughnut)
- **📄 PDF Invoice Processing**: Upload PDF invoices and automatically create vendor bills with AI-powered data extraction
- **Session Management**: Create multiple chat sessions and switch between them
- **Chat History**: All conversations are saved and can be reviewed later
- **Configurable**: Extensive configuration options for AI behavior, model selection, and more

## Installation

### ⚠️ IMPORTANT: Dependency Warning

**This addon has specific version requirements to avoid breaking Odoo v16.**

Newer versions of `pdfplumber` and `Pillow` require `cryptography>=42.0.0`, which is **incompatible** with Odoo v16's `pyOpenSSL 20.0.1` and will break your Odoo instance with SSL errors.

**We have pinned safe versions in `requirements.txt`. DO NOT upgrade them!**

### 1. Prerequisites

- Odoo v16 Community Edition
- Python 3.8+
- **Backup your Odoo instance before installing!**

### 2. Install Dependencies (SAFE METHOD)

**Option A: Using requirements.txt (Recommended)**
```bash
# Install with pinned compatible versions
pip3 install -r requirements.txt --no-deps

# Verify cryptography wasn't upgraded
pip3 show cryptography | grep Version
# Should show: Version: 3.3.2 (NOT 42.x or higher!)
```

**Option B: Manual install**
```bash
# Install exact compatible versions
pip3 install pdfplumber==0.9.0 pandas==1.5.3 Pillow==9.5.0 python-magic==0.4.27
```

**Option C: Virtual Environment (Best Practice)**
```bash
# Create isolated environment
python3 -m venv odoo_ai_chat_venv
source odoo_ai_chat_venv/bin/activate
pip install -r requirements.txt
```

Optional (for better PDF OCR):
```bash
pip3 install pytesseract==0.3.10
apt-get install tesseract-ocr poppler-utils
```

### 3. Install the Module

1. Copy the `odoo_ai_chat` directory to your Odoo addons path
2. Restart the Odoo server
3. Update the Apps list (Apps > Update Apps List)
4. Search for "AI Chat Assistant" and install it

### 🚨 Troubleshooting

**If Odoo breaks after installation with SSL/cryptography errors:**

```bash
# Emergency fix - restore compatible versions
pip3 install --force-reinstall cryptography==3.3.2 pyOpenSSL==20.0.1
# Restart Odoo
```

**Error:** `AttributeError: module 'lib' has no attribute 'X509_V_FLAG_NOTIFY_POLICY'`
- **Cause:** pip upgraded cryptography to version >=42.0.0
- **Fix:** Run the emergency fix above

## Configuration

### 1. Get OpenRouter API Key

1. Visit [OpenRouter](https://openrouter.ai/)
2. Create an account
3. Go to [Keys](https://openrouter.ai/keys) and generate an API key

### 2. Configure the Module

1. Go to **Settings > General Settings**
2. Scroll down to the **AI Chat** section
3. Enter your OpenRouter API key
4. Configure other settings:
   - **AI Model**: Choose the model (e.g., `openai/gpt-3.5-turbo`, `anthropic/claude-3-sonnet`)
   - **Temperature**: Control randomness (0-2, default 0.7)
   - **Max Tokens**: Maximum response length (default 2000)
   - **Enable MCP Tools**: Allow AI to interact with Odoo data (recommended)
   - **System Prompt**: Customize the AI's behavior and personality
5. Click **Save**

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
