# AI Context-Aware Answers - Diagnostic Guide

## Quick Diagnosis Steps

### Step 1: Check if module code is loaded
The recent commit improved context awareness, but Python changes need a restart.

**Action:** Restart Odoo or upgrade the module:
```bash
# Option A: Restart Odoo server
sudo systemctl restart odoo

# Option B: Upgrade module from Odoo UI
Settings → Apps → AI Chat Assistant → Upgrade
```

### Step 2: Verify context is being captured

**Test scenario:**
1. Open a specific record (e.g., Sales → Quotations → Open any order)
2. Click the AI icon in the systray
3. In the chat, ask: "what record am I viewing?"
4. Expected: AI should know the order details
5. Actual: AI says "I don't have enough context"

**Check browser console:**
```
F12 → Console tab → Look for these messages:
[AI Chat] Context tracker service started
[AI Chat] Context updated: {model: 'sale.order', active_id: 123, ...}
[AI Chat] Updating AI channel context: {...}
[AI Chat] AI channel context updated successfully
```

**Check Odoo logs:**
```bash
tail -f /var/log/odoo/odoo-server.log | grep "\[AI Chat\]"

# Expected log messages when navigating:
[AI Chat] update_channel_context called with context: {'model': 'sale.order', 'active_id': 123, ...}
[AI Chat] Got AI channel: 5 (AI Assistant - YourName)
[AI Chat] Context updated successfully for channel 5

# Expected log messages when sending a message:
[AI Chat] View context loaded: {'model': 'sale.order', 'active_id': 123, ...}
[AI Chat] Context age: 12.3 seconds (timestamp: ..., current: ...)
[AI Chat] Building context section for model=sale.order, active_id=123
[AI Chat] Context section built successfully (1245 chars)
```

### Step 3: Common Issues & Solutions

#### Issue A: "No view context stored for channel"
**Cause:** Context updater not running or not sending updates
**Fix:**
1. Clear browser cache (Ctrl+Shift+Delete)
2. Hard refresh the page (Ctrl+Shift+R)
3. Check browser console for JavaScript errors
4. Verify assets are loaded: Check that `context_tracker.js` and `discuss_context_updater.js` are in page source

#### Issue B: "View context is stale (X seconds old), ignoring"
**Cause:** Context older than 5 minutes
**Fix:** This is normal - navigate to a fresh record and ask again within 5 minutes

#### Issue C: "Missing model or active_id in context"
**Cause:** You're in a list view or menu, not viewing a specific record
**Fix:** Open a specific record (form view), then ask the AI

#### Issue D: AI still doesn't recognize context
**Cause:** Using old prompt code
**Fix:**
1. Restart Odoo to reload Python code
2. Clear browser cache
3. Check `mail_channel.py:480` - ensure `_build_context_aware_prompt()` method exists and is used

## Testing the Fix

### Test 1: User Context (should ALWAYS work)
```
You: "What's my name and company?"
AI should respond: "Your name is [YourName] and you're working for [YourCompany]"
```
If this fails → Module code not loaded properly, restart Odoo

### Test 2: View Context (only works when viewing a record)
```
1. Go to: Sales → Quotations → Open SO001
2. Click AI icon
3. Ask: "what's the status of this order?"
AI should respond with the actual order status
```
If this fails → Check logs for context capture issues

### Test 3: From Discuss interface directly
```
1. Click AI icon (opens Discuss)
2. Ask: "do you know where I am?"
AI should respond: "I can see your user context (name, company), but you're currently in the chat interface without viewing a specific record. If you'd like me to help with a specific record, please navigate to it first."
```

## Architecture Reference

### Flow 1: Widget (when using AI chat widget)
```
User sends message
  ↓
ai_chat_widget.js → getCurrentContext()
  ↓
RPC /ai_chat/send_message (with viewContext)
  ↓
main.py:_build_context_aware_prompt(config['system_prompt'], view_context)
  ↓
AI receives: CONFIG prompt + VIEW context + USER context
```

### Flow 2: Discuss (when using systray icon → chat window)
```
User sends message
  ↓
mail_channel.message_post()
  ↓
mail_channel._process_ai_message()
  ↓
mail_channel._build_context_aware_prompt()  # NO config prompt!
  ↓
AI receives: HARDCODED prompt + VIEW context + USER context
```

**Key file:** `mail_channel.py:480-713` - This is the prompt used for Discuss flow

### Context Capture Flow
```
User navigates to record
  ↓
context_tracker.js monitors action.doAction
  ↓
Updates currentContext with {model, active_id, view_type, timestamp}
  ↓
discuss_context_updater.js (every 3s, debounced 500ms)
  ↓
RPC /ai_chat/update_channel_context
  ↓
mail_channel.update_view_context() → stores in current_view_context field
  ↓
When user sends message:
  ↓
mail_channel._get_view_context_section() → builds context prompt section
  ↓
Appended to system prompt IF context exists and is fresh (<5min)
```

## File Reference

| File | Purpose | Key Method |
|------|---------|------------|
| `mail_channel.py:480-713` | Build Discuss prompt | `_build_context_aware_prompt()` |
| `mail_channel.py:597-727` | Build view context section | `_get_view_context_section()` |
| `mail_channel.py:585-596` | Store context from frontend | `update_view_context()` |
| `context_tracker.js:87-100` | Get current view context | `getCurrentContext()` |
| `discuss_context_updater.js:22-53` | Send context to backend | `updateAiChannelContext()` |
| `main.py:715-748` | Context update endpoint | `update_channel_context()` |

## Expected Behavior

### When it works correctly:

**Scenario 1: Viewing a customer (res.partner)**
```
You: "remind me to call this client"
AI: "I'll create a reminder to call [Customer Name]. Let me create an activity for you."
[AI creates activity linked to the customer ID from context]
```

**Scenario 2: Viewing a sales order**
```
You: "what's the status of this order?"
AI: "This sales order [SO001] for [Customer] is currently in [Status] with a total amount of $[Amount]."
```

**Scenario 3: Just chatting (no specific record open)**
```
You: "do you know where I am?"
AI: "I can see you're [Your Name] from [Your Company], but you're not currently viewing a specific record. How can I help you?"
```

### When context is NOT available:

**Acceptable responses:**
- "I can see you're in the chat interface, but I don't have information about a specific record. Which record would you like to work with?"
- "I don't have context about a current record. Could you please specify which customer/order/project you're referring to?"

**Unacceptable responses (indicates broken system):**
- "I don't have access to information about your user account" ← WRONG! User context should ALWAYS be available
- "As an AI assistant, I don't have direct access to your system" ← WRONG! This suggests old/wrong prompt

## Next Steps

1. **Restart Odoo** to load the new prompt code
2. **Test with the 3 test scenarios** above
3. **Check logs** if any test fails
4. **Report findings** with:
   - Which tests passed/failed
   - Relevant log messages
   - Browser console messages
