# OdooMCP AI Chat Addon - Architecture Analysis & Discuss Module Integration

## EXECUTIVE SUMMARY

The `odoo_ai_chat` addon is a **completely self-contained, standalone chat widget** that operates independently from Odoo's core mail/messaging infrastructure. It has its own custom data models, UI components, and communication patterns. Integration with the Discuss module would require substantial architectural changes and rewrites of core components.

---

## CURRENT ARCHITECTURE

### 1. WIDGET IMPLEMENTATION

#### Structure
- **Framework**: Owl.js (Odoo's modern web component framework)
- **Type**: Client-side action (`ir.actions.client` with tag `"ai_chat_widget"`)
- **Deployment**: Systray icon that opens as a modal dialog
- **Dimensions**: 800px × 600px responsive dialog

#### Key Files
- `/odoo_ai_chat/static/src/js/ai_chat_widget.js` (373 lines) - Main component
- `/odoo_ai_chat/static/src/js/systray_item.js` (37 lines) - Systray integration
- `/odoo_ai_chat/static/src/xml/ai_chat_templates.xml` - Owl templates
- `/odoo_ai_chat/static/src/css/ai_chat.css` (406 lines) - Custom styling

#### Component Tree
```
AIChatSystrayItem
  └─ Opens dialog with AIChatWidget (Owl component)
      ├─ Header
      │  ├─ Toggle Sessions Sidebar button
      │  ├─ "AI Chat Assistant" title
      │  └─ "New Chat" button
      ├─ Body
      │  ├─ Sessions Sidebar (collapsible)
      │  │  └─ List of chat sessions with metadata
      │  └─ Messages Container
      │     ├─ Welcome message or message list
      │     ├─ Messages display area
      │     ├─ Typing indicator animation
      │     └─ Input area with attachment & send buttons
      └─ State Management
         ├─ messages: []
         ├─ sessions: []
         ├─ currentSessionId
         ├─ inputMessage
         ├─ loading state
         ├─ uploadingFile state
         └─ showSessions state
```

### 2. DATA MODELS

#### AI Chat Session Model (`ai.chat.session`)
**Location**: `/odoo_ai_chat/models/ai_chat_session.py`

| Field | Type | Description |
|-------|------|-------------|
| `name` | Char | Session name (auto-generated from first message) |
| `user_id` | Many2one(res.users) | Owner of the session |
| `message_ids` | One2many(ai.chat.message) | Related messages |
| `message_count` | Integer | Computed, count of messages |
| `last_message_date` | Datetime | Computed, latest message timestamp |
| `active` | Boolean | Soft delete support |

**Methods**:
- `action_archive()` - Archive session
- `action_unarchive()` - Restore archived session
- `get_messages_for_api()` - Return messages formatted for AI API calls

#### AI Chat Message Model (`ai.chat.message`)
**Location**: `/odoo_ai_chat/models/ai_chat_message.py`

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | Many2one(ai.chat.session) | Parent session |
| `role` | Selection | Values: 'user', 'assistant', 'system', 'tool' |
| `content` | Text | Message content |
| `tool_calls` | Text | JSON of tool calls made by assistant |
| `tool_call_id` | Char | ID linking tool response to call |
| `metadata` | Text | JSON for additional data (graph_data, etc.) |
| `tokens_used` | Integer | Token count for tracking API usage |

**Key Design**: 
- Mirrors OpenAI's message format (role/content)
- Supports tool call tracking via OpenRouter
- No connection to mail module's fields

### 3. SERVICE LAYER

#### JavaScript Service (`ai_chat_service`)
**Location**: `/odoo_ai_chat/static/src/js/ai_chat_service.js`

**Architecture**: Custom event-based service with internal caching

```javascript
// Service Methods
sendMessage(message, sessionId)      // POST to /ai_chat/send_message
getSessions()                        // GET sessions list
getMessages(sessionId)               // GET messages for session
newSession(name)                     // Create new session
deleteSession(sessionId)             // Delete session
addEventListener(callback)           // Subscribe to service events
getCurrentMessages()                 // Get cached messages
getCurrentSessionId()                // Get active session ID

// Events
'message' - Single message added
'sessions' - Sessions list updated
'messages' - Message thread updated
'new_session' - New session created
'delete_session' - Session deleted
```

**Design Pattern**: Simple pub-sub with in-memory caching of:
- `currentSessionId`
- `sessions[]` array
- `messages[]` array

### 4. BACKEND CONTROLLER

**Location**: `/odoo_ai_chat/controllers/main.py`

#### Endpoints
| Route | Method | Purpose |
|-------|--------|---------|
| `/ai_chat/send_message` | JSON-RPC | Send message to AI |
| `/ai_chat/get_sessions` | JSON-RPC | Fetch user's sessions |
| `/ai_chat/get_messages` | JSON-RPC | Fetch messages for session |
| `/ai_chat/delete_session` | JSON-RPC | Delete a session |
| `/ai_chat/new_session` | JSON-RPC | Create new session |
| `/ai_chat/upload_pdf` | HTTP POST | Upload PDF for processing |
| `/ai_chat/process_invoice` | JSON-RPC | Process PDF as invoice |

#### Message Sending Flow
```
send_message()
├─ Validate/create session
├─ Create user message record (ai.chat.message)
├─ Get AI config (OpenRouter API key, model, etc.)
├─ Build message list from session history
├─ Call OpenRouter API
├─ Handle tool calls if enabled
│  └─ Execute MCP tools
│  └─ Call AI again with tool results
└─ Create assistant message record
└─ Return response to frontend
```

### 5. UI/UX ELEMENTS

#### Visual Design
- **Color Scheme**: Purple gradient (#875a7b to #a24689)
- **Typography**: Bootstrap default
- **Icons**: Font Awesome + emoji (🤖 robot)
- **Layout**: Two-column with collapsible sidebar

#### Key UI Components
1. **Messages Display**
   - User messages: Purple bubble, right-aligned
   - Assistant messages: Gray bubble, left-aligned
   - Typing indicator: 3 animated dots
   - Message timestamps: Relative format (e.g., "2 days ago")

2. **Session Sidebar**
   - Session name (truncated)
   - Message count and last message date
   - Delete button (trash icon)
   - Active state highlighting
   - Collapsible (hidden on mobile)

3. **Input Area**
   - Rounded textarea (2-3 rows)
   - Attachment button (paperclip icon)
   - Send button (paper-plane icon)
   - File input validation (PDF only, 10MB max)
   - Disable state when loading/uploading

4. **Tool Call Indicators**
   - Blue badge showing "Used tools: [tool_names]"
   - Graph rendering with Chart.js for data visualization
   - Tool results shown as part of conversation

#### Styling Notes
- Fixed-width widget (800px) with responsive fallback
- Smooth animations (fadeIn on messages, typing indicator)
- Scrolls to bottom automatically on new messages
- Custom scrollbar styling

### 6. DEPENDENCIES

#### Python Dependencies
- `requests` - For OpenRouter API calls
- `pandas` - For chart/graph generation (optional)
- `pytesseract` - For PDF text extraction
- Standard library: `json`, `logging`, `base64`, `threading`

#### JavaScript Dependencies
- `Chart.js@4.4.0` - Chart rendering library
- Odoo `@odoo/owl` - Component framework
- Odoo `@web/core/registry` - Service/component registration
- Odoo `@web/core/utils/hooks` - useService, etc.
- Odoo `@web/core/network/rpc_service` - RPC calls

#### Odoo Dependencies (from manifest)
```python
'depends': ['base', 'web'],
```

**NO dependency on `mail` or `discuss` modules**

### 7. ADDITIONAL FEATURES

#### OpenRouter AI Integration
- Dynamic model dropdown (fetches from OpenRouter API)
- Temperature control (0-2 scale)
- Max tokens configuration
- System prompt customization
- Site URL/name for attribution

#### MCP (Model Context Protocol) Tools
- Tool calling support for AI to interact with Odoo data
- Available tools: search_records, read_record, create_record, write_record, generate_graph, etc.
- Tool execution with result caching
- Graph generation from data

#### PDF Processing
- Invoice/vendor bill creation from uploaded PDFs
- OCR text extraction
- Automatic bill line item generation
- Vendor matching and creation

---

## COMPARISON: CURRENT VS. DISCUSS MODULE

### Current Architecture
```
OdooMCP AI Chat Widget
├─ Standalone custom component
├─ Own data models (ai.chat.session, ai.chat.message)
├─ Systray-based UI entry point
├─ OpenAI/OpenRouter provider integration
├─ MCP tool integration for Odoo interaction
└─ No email/notification integration
```

### Odoo Discuss Module (Core)
```
Odoo Discuss
├─ Built on mail.message model
├─ mail.thread mixin for document threading
├─ Channels & Direct Messages support
├─ Follower/notification system
├─ Email integration (incoming/outgoing)
├─ Activity tracking
├─ Mention & tagging system
├─ Embedded in document forms (chatter widget)
└─ ACL controlled by followers
```

### Key Differences

| Aspect | Current AI Chat | Discuss Module |
|--------|-----------------|----------------|
| **Data Model** | Custom ai.chat.message | mail.message (OpenERP protocol) |
| **UI Location** | Systray → Modal Dialog | Embedded in form (chatter) |
| **Threading** | Session-based chats | Document-based threads (mail.thread) |
| **Recipients** | Individual only | Groups, channels, followers |
| **Email** | PDF-only processing | Full email integration |
| **Notifications** | None | Email/Odoo notifications |
| **Access Control** | User-scoped sessions | Follower-based with mail.followers |
| **Rich Content** | Text + embedded charts | Text + attachments + activities |
| **API Integration** | OpenRouter + MCP | SMTP/IMAP |

---

## INTEGRATION REQUIREMENTS

### What Integration Would Involve

If you wanted to integrate AI Chat with Discuss (embed AI in document chatter), you would need to:

#### 1. **Data Model Changes** (High Impact)
```python
# Current: Custom models only
ai.chat.session
ai.chat.message

# New: Mix with mail.message
ai.chat.message extends mail.message?
OR
Map ai.chat.message to mail.message records
```

**Challenges**:
- `mail.message` has different field structure (author_id, model, res_id, subtype_id)
- `ai.chat.message` is simpler (just role/content)
- Tool calls and metadata don't fit mail.message schema
- Would need migration strategy

#### 2. **Threading Model Changes** (High Impact)
```python
# Current: Flat sessions with independent messages
- Session 1 (user_id)
  - Message 1 (user)
  - Message 2 (assistant)

# Discuss model: Document-threaded conversations
- Document (sale.order, etc.)
  - mail.thread mixing:
    - Email messages
    - Internal notes
    - AI responses (?)
    - Activities
    - Followers
```

**Challenges**:
- AI chats are not bound to documents by default
- Would need to add `res_model` and `res_id` fields
- Requires deciding: AI chat per document or global?

#### 3. **UI Component Rewrite** (High Impact)
```javascript
// Current: Standalone modal
ir.actions.client (ai_chat_widget)

// Discuss: Embedded message thread
// Would need to:
// 1. Create a custom "thread message" template
// 2. Embed in chatter widget (already exists in base)
// 3. Add AI response button/trigger in forms
// 4. Implement real-time updates with bus
```

**Challenges**:
- Current service-based architecture needs real-time bus integration
- Message rendering would differ (mail.message has different template)
- Session sidebar wouldn't fit in chatter context
- Would need WebSocket support (Odoo's long-polling bus)

#### 4. **Service Layer Refactoring** (Medium Impact)
```javascript
// Current: Custom service with polling
aiChatService
├─ Manual RPC calls
├─ In-memory caching
└─ Event listener pattern

// Discuss: Would use mail message bus
mailService or discussService
├─ Real-time bus for notifications
├─ mail.message subscription/listening
└─ Follower notification system
```

#### 5. **Security & Access Control** (Medium Impact)
```python
# Current: User-scoped only
- Session.user_id = current_user
- Only owner can see own chats

# Discuss: Follower-based
- mail.followers for access control
- Shared documents need shared AI chat
- Mail module's ACL system
- Cross-user threads
```

**Challenges**:
- Would need to extend mail.followers
- Implement mail.notification integration
- Handle document-based visibility

#### 6. **Email/Notification Integration** (Medium Impact)
```python
# Current: No email integration
- AI responses only visible in UI
- No outgoing emails
- No incoming email threading

# Discuss: Full email support
- Outgoing emails for mentioned users
- Incoming email threads with AI
- Catchall address integration
- Email notification preferences
```

#### 7. **Dependency Changes** (Low Impact)
```python
# Current
'depends': ['base', 'web']

# New
'depends': ['base', 'web', 'mail', 'discuss']
```

---

## EFFORT ESTIMATION

If you wanted to implement Discuss integration, here's the scope:

### Phase 1: Data Model Migration (2-3 weeks)
- [ ] Design unified message model (extend mail.message or create hybrid)
- [ ] Migration script for existing ai.chat.message data
- [ ] Add document threading support
- [ ] Implement follower/ACL system
- [ ] Tests for data integrity

### Phase 2: Backend Refactoring (3-4 weeks)
- [ ] Rewrite controller to use mail models
- [ ] Implement mail.notification integration
- [ ] Add email handling for AI responses
- [ ] Update OpenRouter integration with mail context
- [ ] Implement real-time message bus integration
- [ ] Tests for all endpoints

### Phase 3: Frontend UI Rewrite (3-4 weeks)
- [ ] Create mail-compatible message templates
- [ ] Embed in chatter widget
- [ ] Implement real-time message updates (bus)
- [ ] Add follower notification UI
- [ ] Remove/adapt session sidebar
- [ ] Mobile responsiveness updates
- [ ] Tests for UI interactions

### Phase 4: Integration & Polish (2 weeks)
- [ ] Email integration testing
- [ ] Notification system testing
- [ ] Cross-browser/device testing
- [ ] Performance optimization
- [ ] Documentation

**Total: 10-15 weeks** for complete Discuss integration

---

## ALTERNATIVE APPROACH: HYBRID INTEGRATION

Rather than full integration, you could:

1. **Keep Current AI Chat Separate** + Add Bridge
   - Keep systray widget as-is
   - Add optional "Link to Document" feature
   - Store reference in ai.chat.session to document
   - Allows sharing in document context without full refactor
   - **Effort: 2-3 weeks**

2. **Add Discussion Context to AI**
   - When opening AI chat from a document, pass context
   - Inject document data into AI system prompt
   - Let AI reference document context without storing in mail
   - **Effort: 1-2 weeks**

3. **Create AI-Specific Channel**
   - Create a Discuss channel just for AI responses
   - Add AI chat messages as mail.message records
   - Keep sessions separate but sync to channel
   - **Effort: 3-4 weeks**

---

## SUMMARY: SHOULD YOU INTEGRATE?

### Reasons TO integrate with Discuss:
✓ Unified messaging interface
✓ Email notifications for AI responses
✓ Share AI insights with team members
✓ Document-based AI chat (one per sale order, etc.)
✓ Activity tracking on documents
✓ Follower notifications

### Reasons NOT to integrate:
✗ Significant development effort (10-15 weeks)
✗ mail.message structure is different (not designed for tool calls, graphs)
✗ Existing functionality doesn't need email
✗ Systray widget works well for global AI assistant role
✗ Document linking is optional use case
✗ More complexity in permissions/access control

### Recommended Path:
**Hybrid Approach** - Keep current architecture, add optional document linking
- Minimal code changes
- Users get best of both: standalone AI + document context
- Can always upgrade to full integration later
- **2-3 weeks effort** instead of 10-15

---

## CODE LOCATIONS REFERENCE

**Frontend**:
- Widget: `/odoo_ai_chat/static/src/js/ai_chat_widget.js`
- Service: `/odoo_ai_chat/static/src/js/ai_chat_service.js`
- Templates: `/odoo_ai_chat/static/src/xml/ai_chat_templates.xml`
- Styling: `/odoo_ai_chat/static/src/css/ai_chat.css`
- Systray: `/odoo_ai_chat/static/src/js/systray_item.js`

**Backend**:
- Controller: `/odoo_ai_chat/controllers/main.py`
- Models: `/odoo_ai_chat/models/ai_chat_session.py`, `ai_chat_message.py`
- Provider: `/odoo_ai_chat/models/ai_provider.py`
- MCP: `/odoo_ai_chat/models/mcp_server.py`
- PDF Processing: `/odoo_ai_chat/models/pdf_processor.py`

**Configuration**:
- Manifest: `/odoo_ai_chat/__manifest__.py`
- Views: `/odoo_ai_chat/views/ai_chat_views.xml`
- Settings: `/odoo_ai_chat/views/res_config_settings_views.xml`

