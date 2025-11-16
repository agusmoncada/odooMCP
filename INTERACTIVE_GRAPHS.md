# Interactive Graphs in Odoo Discuss

## Current Implementation (Static Images)
Currently, graphs are rendered as static PNG images using matplotlib:
- ✅ Simple, reliable, works everywhere
- ✅ No JavaScript required
- ✅ Embedded directly in messages
- ❌ Not interactive (can't hover, zoom, filter)

## Interactive Graphs - Implementation Options

### Option 1: Chart.js (Recommended)
**How it works:**
1. Include Chart.js library in Odoo web assets
2. Generate HTML with a canvas element and data
3. Inject JavaScript that renders the chart
4. Odoo's sanitizer needs to allow the script tags

**Pros:**
- Lightweight (~200KB)
- Beautiful, modern charts
- Interactive (hover, tooltips, zoom)
- Responsive
- Well-documented

**Cons:**
- Requires modifying Odoo's HTML sanitization rules
- JavaScript must be allowed in mail messages (security risk)
- Chart state not persisted (reloads on refresh)

**Implementation:**

```python
# In mcp_server.py
def _render_interactive_graph(self, graph_type, labels, values, title):
    """Render interactive chart using Chart.js"""

    chart_id = f"chart_{uuid.uuid4().hex[:8]}"

    html = f'''
    <div style="position: relative; height:400px; width:600px; margin: 20px auto;">
        <canvas id="{chart_id}"></canvas>
    </div>
    <script src="/odoo_ai_chat/static/lib/chart.min.js"></script>
    <script>
        (function() {{
            var ctx = document.getElementById('{chart_id}').getContext('2d');
            new Chart(ctx, {{
                type: '{graph_type}',
                data: {{
                    labels: {json.dumps(labels)},
                    datasets: [{{
                        label: '{title}',
                        data: {json.dumps(values)},
                        backgroundColor: '#875A7B',
                        borderColor: '#6B4562',
                        borderWidth: 2
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            display: true
                        }},
                        tooltip: {{
                            enabled: true
                        }}
                    }}
                }}
            }});
        }})();
    </script>
    '''
    return html
```

**Required Changes:**
1. Add Chart.js to static assets:
   ```
   odoo_ai_chat/static/lib/chart.min.js
   ```

2. Allow script tags in mail messages (RISKY!):
   ```python
   # In mail_channel.py
   def message_post(self, **kwargs):
       if self.is_ai_channel and kwargs.get('body'):
           # Bypass sanitization for AI messages
           kwargs['body'] = Markup(kwargs['body'])
       return super().message_post(**kwargs)
   ```

3. Load Chart.js in mail view:
   ```xml
   <!-- In views/mail_assets.xml -->
   <template id="mail_assets_backend" inherit_id="web.assets_backend">
       <xpath expr="." position="inside">
           <script type="text/javascript" src="/odoo_ai_chat/static/lib/chart.min.js"/>
       </xpath>
   </template>
   ```

### Option 2: Plotly.js
**Similar to Chart.js but:**
- More powerful (3D, scientific charts)
- Larger file size (~3MB)
- Same security concerns
- More complex API

### Option 3: Embedded iframe with external charting service
**How it works:**
1. Send chart data to external service (e.g., QuickChart.io, Chart.io)
2. Get back iframe URL
3. Embed iframe in message

**Pros:**
- No JavaScript in messages (safer)
- Professional charts
- Works with Odoo's sanitization

**Cons:**
- External dependency
- Privacy concerns (data leaves your server)
- Requires internet connection
- May have rate limits/costs

**Implementation:**
```python
def _render_chart_via_service(self, graph_type, labels, values, title):
    """Use QuickChart.io to render chart"""
    import urllib.parse

    chart_config = {
        'type': graph_type,
        'data': {
            'labels': labels,
            'datasets': [{
                'label': title,
                'data': values,
                'backgroundColor': '#875A7B'
            }]
        }
    }

    encoded_config = urllib.parse.quote(json.dumps(chart_config))
    chart_url = f"https://quickchart.io/chart?c={encoded_config}"

    # Return as image (static but from external service)
    return f'<img src="{chart_url}" alt="{title}" style="max-width:100%; height:auto;"/>'
```

### Option 4: Odoo Web Components (Best for Odoo)
**How it works:**
1. Create a custom Odoo web widget for charts
2. Store chart data in a transient model
3. Render widget in message using QWeb template
4. Widget handles interactivity client-side

**Pros:**
- Native Odoo approach
- Secure (no script injection)
- Persistent chart data
- Full control over rendering

**Cons:**
- Most complex implementation
- Requires Odoo JS framework knowledge
- More code to maintain

**Implementation Steps:**
1. Create chart data model:
   ```python
   class AIChatGraph(models.TransientModel):
       _name = 'ai.chat.graph'
       _description = 'AI Chat Graph Data'

       chart_type = fields.Selection([('bar', 'Bar'), ('line', 'Line'), ('pie', 'Pie')])
       labels = fields.Text()  # JSON
       values = fields.Text()  # JSON
       title = fields.Char()
   ```

2. Create JavaScript widget:
   ```javascript
   // static/src/js/chart_widget.js
   odoo.define('odoo_ai_chat.ChartWidget', function (require) {
       var AbstractField = require('web.AbstractField');
       var fieldRegistry = require('web.field_registry');

       var ChartWidget = AbstractField.extend({
           template: 'ChartWidget',

           start: function () {
               this._super.apply(this, arguments);
               this._renderChart();
           },

           _renderChart: function () {
               var chartData = JSON.parse(this.value);
               var ctx = this.$el.find('canvas')[0].getContext('2d');
               new Chart(ctx, chartData);
           }
       });

       fieldRegistry.add('chart_widget', ChartWidget);
   });
   ```

3. Embed in message:
   ```python
   # Create graph record
   graph = self.env['ai.chat.graph'].create({
       'chart_type': 'bar',
       'labels': json.dumps(labels),
       'values': json.dumps(values),
       'title': title
   })

   # Reference in message
   html = f'<div class="o_chart_widget" data-graph-id="{graph.id}"></div>'
   ```

## Security Considerations

### ⚠️ CRITICAL: Script Injection Risk
Allowing `<script>` tags in mail messages is a **security vulnerability**:
- Users could inject malicious JavaScript
- XSS attacks possible
- Only do this if AI messages are STRICTLY controlled

### Recommended Approach:
1. **Static images (current)** - Safest, works everywhere
2. **External service** - Safe, but external dependency
3. **Odoo widgets** - Safe, complex but proper architecture
4. **Chart.js with script tags** - Only if AI channel messages are isolated and users cannot inject content

## Recommendation

**For production use:**
- Keep static images (current implementation) ✅
- They work, they're safe, they're simple
- Matplotlib is widely compatible with Odoo v16

**For enhanced UX (if needed):**
- Use **Option 4 (Odoo Web Components)** for proper integration
- Or use **Option 3 (External service)** for quick interactive charts without security risks

**Avoid:**
- Injecting `<script>` tags directly in messages (Option 1/2) unless you fully isolate AI channels from user input

## Would Interactive Graphs Be Worth It?

**Probably not**, because:
1. Static images work well for Discuss (it's a chat, not a dashboard)
2. Security risks of allowing scripts in messages
3. Charts don't need to be interactive in chat context (no drill-down needed)
4. Users can always open the full view if they need interactivity

**Use cases where interactive makes sense:**
- Dedicated dashboard views (use Odoo's native graph views)
- Embedded analytics pages (use Chart.js in QWeb templates)
- Custom kanban/list view widgets (use Odoo widgets)

**For Discuss:**
- Static images are perfect ✅
- Fast, secure, simple
- If user needs more detail, AI can provide drill-down data or link to records
