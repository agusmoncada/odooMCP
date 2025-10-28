# Future Features Implementation Guide

This document outlines how to extend the AI Chat Assistant addon to support advanced features like graph generation and PDF invoice processing.

---

## Feature 1: Graph Generation

### Overview
Allow the AI to create visual graphs and charts based on Odoo data (sales trends, revenue charts, customer analytics, etc.).

### Approach Options

#### Option A: Return Graph Data (Recommended)
The AI returns structured data that the frontend renders using Chart.js or similar.

**Advantages:**
- Interactive graphs in the chat
- Lightweight (no image generation)
- Easy to customize and style
- Mobile-friendly

#### Option B: Generate Image Files
The AI generates actual image files (PNG/SVG) and returns them.

**Advantages:**
- Can be downloaded/shared easily
- Works in any context
- No frontend dependencies

### Implementation Steps

#### 1. Add Required Dependencies

```bash
# For Option A (recommended)
pip3 install pandas

# For Option B (image generation)
pip3 install matplotlib pandas
```

#### 2. Create New MCP Tool: `generate_graph`

**File:** `odoo_ai_chat/models/mcp_server.py`

Add to `_initialize_tools()` method:

```python
'generate_graph': {
    'name': 'generate_graph',
    'description': 'Generate a graph/chart from Odoo data',
    'inputSchema': {
        'type': 'object',
        'properties': {
            'graph_type': {
                'type': 'string',
                'enum': ['line', 'bar', 'pie', 'area', 'scatter'],
                'description': 'Type of graph to generate'
            },
            'model': {
                'type': 'string',
                'description': 'Odoo model to query (e.g., sale.order)'
            },
            'domain': {
                'type': 'array',
                'description': 'Search domain for filtering records'
            },
            'x_field': {
                'type': 'string',
                'description': 'Field for X axis (e.g., create_date, date_order)'
            },
            'y_field': {
                'type': 'string',
                'description': 'Field for Y axis (e.g., amount_total)'
            },
            'group_by': {
                'type': 'string',
                'description': 'Optional field to group by'
            },
            'title': {
                'type': 'string',
                'description': 'Graph title'
            },
            'date_range': {
                'type': 'string',
                'enum': ['week', 'month', 'quarter', 'year', 'all'],
                'description': 'Time range for date-based graphs'
            }
        },
        'required': ['graph_type', 'model', 'y_field']
    }
}
```

Add the method to handle it:

```python
def _generate_graph(self, graph_type: str, model: str, y_field: str,
                    x_field: str = None, domain: List = None,
                    group_by: str = None, title: str = None,
                    date_range: str = 'month') -> Dict:
    """Generate graph data from Odoo records"""
    try:
        import pandas as pd
        from datetime import datetime, timedelta

        Model = self.env[model]

        # Apply date range to domain
        if x_field and 'date' in x_field.lower():
            domain = domain or []
            if date_range != 'all':
                days_map = {'week': 7, 'month': 30, 'quarter': 90, 'year': 365}
                days = days_map.get(date_range, 30)
                cutoff_date = datetime.now() - timedelta(days=days)
                domain.append((x_field, '>=', cutoff_date.strftime('%Y-%m-%d')))

        # Fetch records
        records = Model.search(domain or [])

        if not records:
            return {'success': False, 'error': 'No records found'}

        # Read data
        fields_to_read = [y_field]
        if x_field:
            fields_to_read.append(x_field)
        if group_by:
            fields_to_read.append(group_by)

        data = records.read(fields_to_read)
        df = pd.DataFrame(data)

        # Process based on graph type
        if group_by:
            # Aggregate by group
            if graph_type == 'pie':
                result_data = df.groupby(group_by)[y_field].sum().to_dict()
                labels = list(result_data.keys())
                values = list(result_data.values())
            else:
                grouped = df.groupby(group_by)[y_field].sum().reset_index()
                labels = grouped[group_by].tolist()
                values = grouped[y_field].tolist()
        elif x_field:
            # Time series or x-y graph
            df_sorted = df.sort_values(by=x_field)
            labels = df_sorted[x_field].tolist()
            values = df_sorted[y_field].tolist()

            # Format dates if applicable
            if isinstance(labels[0], datetime):
                labels = [d.strftime('%Y-%m-%d') for d in labels]
        else:
            # Simple aggregation
            labels = ['Total']
            values = [df[y_field].sum()]

        # Return structured data for frontend rendering
        return {
            'success': True,
            'graph_data': {
                'type': graph_type,
                'title': title or f'{y_field} Analysis',
                'labels': labels,
                'datasets': [{
                    'label': y_field.replace('_', ' ').title(),
                    'data': values
                }],
                'record_count': len(records)
            }
        }

    except Exception as e:
        _logger.exception("Error generating graph")
        return {'success': False, 'error': str(e)}
```

Add to `call_tool()` method:

```python
elif tool_name == 'generate_graph':
    return self._generate_graph(**arguments)
```

#### 3. Update Frontend to Render Graphs

**Add Chart.js to manifest:**

```python
# In __manifest__.py, add to assets
'web.assets_backend': [
    # ... existing files ...
    ('include', 'web._assets_helpers'),
    'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
    'odoo_ai_chat/static/src/js/chart_renderer.js',
],
```

**Create Chart Renderer:**

**File:** `odoo_ai_chat/static/src/js/chart_renderer.js`

```javascript
/** @odoo-module **/

export class ChartRenderer {
    constructor(canvasElement, graphData) {
        this.canvas = canvasElement;
        this.data = graphData;
        this.chart = null;
    }

    render() {
        const config = {
            type: this.data.type,
            data: {
                labels: this.data.labels,
                datasets: this.data.datasets.map(ds => ({
                    ...ds,
                    backgroundColor: this._getColors(this.data.type),
                    borderColor: '#875a7b',
                    borderWidth: 2
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: this.data.title
                    },
                    legend: {
                        display: this.data.type === 'pie'
                    }
                }
            }
        };

        this.chart = new Chart(this.canvas, config);
        return this.chart;
    }

    _getColors(type) {
        const colors = [
            '#875a7b', '#a24689', '#6d4861', '#b35a9a',
            '#5a4561', '#c76baa', '#4a3551', '#d77cba'
        ];

        if (type === 'pie') {
            return colors;
        }
        return 'rgba(135, 90, 123, 0.2)';
    }

    destroy() {
        if (this.chart) {
            this.chart.destroy();
        }
    }
}
```

**Update Chat Widget to Handle Graphs:**

**File:** `odoo_ai_chat/static/src/js/ai_chat_widget.js`

Add method to detect graph data:

```javascript
/**
 * Check if message contains graph data
 */
hasGraphData(message) {
    try {
        if (message.tool_calls) {
            const toolCalls = JSON.parse(message.tool_calls);
            return toolCalls.some(tc => tc.name === 'generate_graph');
        }
    } catch (e) {}
    return false;
}

/**
 * Extract graph data from message
 */
getGraphData(message) {
    // Implementation depends on how you structure the response
    // The AI provider should include graph_data in the tool result
    return message.graph_data;
}
```

**Update Template:**

```xml
<!-- Add to ai_chat_templates.xml -->
<t t-if="message.graph_data">
    <div class="o_ai_chat_graph">
        <canvas t-att-id="'chart_' + message.id"
                style="max-height: 300px;"/>
    </div>
</t>
```

---

## Feature 2: PDF Invoice Processing

### Overview
Allow users to upload PDF invoices, which the AI will parse and automatically create as vendor bills in Odoo.

### Approach

Use OCR and PDF parsing to extract:
- Vendor information
- Invoice number and date
- Line items (products, quantities, prices)
- Totals and taxes

### Implementation Steps

#### 1. Add Required Dependencies

```bash
pip3 install PyPDF2 pdfplumber python-magic pdf2image
pip3 install pytesseract  # For OCR if needed

# System dependencies
apt-get install tesseract-ocr  # For OCR
apt-get install poppler-utils  # For PDF to image conversion
```

For better results, consider using AI-powered services:
- OpenAI Vision API
- Google Cloud Vision
- AWS Textract
- Azure Form Recognizer

#### 2. Add File Upload to Frontend

**Update Chat Widget Template:**

```xml
<!-- Add to input area in ai_chat_templates.xml -->
<div class="o_ai_chat_input_container">
    <div class="o_ai_chat_input">
        <button class="btn btn-sm btn-secondary" t-on-click="onAttachFile">
            <i class="fa fa-paperclip"/>
        </button>
        <textarea ... />
        <button class="btn btn-primary" t-on-click="sendMessage">
            <i class="fa fa-paper-plane"/>
        </button>
    </div>
    <input type="file"
           t-ref="fileInput"
           style="display: none;"
           accept=".pdf"
           t-on-change="onFileSelected"/>
</div>
```

**Update Widget JavaScript:**

```javascript
// In ai_chat_widget.js

onAttachFile() {
    this.fileInputRef = useRef("fileInput");
    if (this.fileInputRef.el) {
        this.fileInputRef.el.click();
    }
}

async onFileSelected(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (file.type !== 'application/pdf') {
        this.notification.add("Please select a PDF file", {
            type: "warning",
        });
        return;
    }

    try {
        this.state.loading = true;

        // Upload file
        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', this.state.currentSessionId);

        const response = await fetch('/ai_chat/upload_pdf', {
            method: 'POST',
            body: formData,
        });

        const result = await response.json();

        if (result.success) {
            // Add a message about the uploaded file
            this.state.inputMessage = `Process this invoice: ${file.name}`;
            await this.sendMessage();
        } else {
            this.notification.add(result.error || "Failed to upload file", {
                type: "danger",
            });
        }
    } catch (error) {
        this.notification.add("Failed to upload file", {
            type: "danger",
        });
    } finally {
        this.state.loading = false;
        event.target.value = ''; // Reset input
    }
}
```

#### 3. Create PDF Processing Tool

**File:** `odoo_ai_chat/models/pdf_processor.py`

```python
"""PDF Invoice Processing"""

import logging
import base64
import json
from typing import Dict, Optional

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False

_logger = logging.getLogger(__name__)


class PDFInvoiceProcessor:
    """Process PDF invoices and extract data"""

    def __init__(self, env):
        self.env = env

    def process_pdf(self, pdf_content: bytes, filename: str) -> Dict:
        """
        Process PDF and extract invoice data

        Args:
            pdf_content: PDF file content as bytes
            filename: Original filename

        Returns:
            Dict with extracted invoice data
        """
        if not PDFPLUMBER_AVAILABLE:
            return {
                'success': False,
                'error': 'PDF processing library not available. Install pdfplumber.'
            }

        try:
            # Extract text from PDF
            text = self._extract_text(pdf_content)

            # Use AI to parse the invoice text
            invoice_data = self._parse_with_ai(text, filename)

            return {
                'success': True,
                'data': invoice_data,
                'raw_text': text[:500]  # First 500 chars for reference
            }

        except Exception as e:
            _logger.exception("Error processing PDF")
            return {
                'success': False,
                'error': str(e)
            }

    def _extract_text(self, pdf_content: bytes) -> str:
        """Extract text from PDF"""
        import io

        text_parts = []

        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)

        return '\n'.join(text_parts)

    def _parse_with_ai(self, text: str, filename: str) -> Dict:
        """
        Use AI to parse invoice text and extract structured data

        This method should:
        1. Send the text to OpenRouter with a specialized prompt
        2. Request structured JSON output
        3. Return parsed invoice data
        """
        # Get AI config
        config = self.env['res.config.settings'].get_ai_config()

        from .ai_provider import OpenRouterProvider

        ai_provider = OpenRouterProvider(
            api_key=config['api_key'],
            model=config['model'],
            site_url=config['site_url'],
            site_name=config['site_name']
        )

        # Specialized prompt for invoice extraction
        prompt = f"""Extract invoice information from the following text and return a JSON object with this structure:
{{
    "vendor_name": "Company name",
    "vendor_vat": "Tax ID if available",
    "invoice_number": "Invoice reference number",
    "invoice_date": "Date in YYYY-MM-DD format",
    "due_date": "Due date in YYYY-MM-DD format if available",
    "currency": "Currency code (USD, EUR, etc.)",
    "lines": [
        {{
            "description": "Product/service description",
            "quantity": 1.0,
            "unit_price": 100.0,
            "tax_amount": 0.0,
            "subtotal": 100.0
        }}
    ],
    "subtotal": 100.0,
    "tax_total": 0.0,
    "total": 100.0,
    "notes": "Any additional notes or terms"
}}

Invoice text:
{text}

Return ONLY the JSON object, no additional text."""

        messages = [
            {'role': 'system', 'content': 'You are an expert at extracting structured data from invoices. Always respond with valid JSON only.'},
            {'role': 'user', 'content': prompt}
        ]

        response = ai_provider.chat(messages=messages, temperature=0.1)

        # Extract and parse JSON from response
        ai_text = response.get('choices', [{}])[0].get('message', {}).get('content', '')

        # Try to parse JSON
        try:
            # Remove markdown code blocks if present
            if '```json' in ai_text:
                ai_text = ai_text.split('```json')[1].split('```')[0].strip()
            elif '```' in ai_text:
                ai_text = ai_text.split('```')[1].split('```')[0].strip()

            invoice_data = json.loads(ai_text)
            return invoice_data

        except json.JSONDecodeError as e:
            _logger.error(f"Failed to parse AI response as JSON: {ai_text}")
            return {
                'error': 'Failed to parse invoice data',
                'raw_response': ai_text
            }
```

#### 4. Create MCP Tool: `create_vendor_bill_from_pdf`

**Add to `mcp_server.py`:**

```python
'create_vendor_bill_from_pdf': {
    'name': 'create_vendor_bill_from_pdf',
    'description': 'Create a vendor bill from parsed PDF invoice data',
    'inputSchema': {
        'type': 'object',
        'properties': {
            'invoice_data': {
                'type': 'object',
                'description': 'Parsed invoice data from PDF'
            },
            'pdf_content': {
                'type': 'string',
                'description': 'Base64 encoded PDF content (optional, for attachment)'
            },
            'filename': {
                'type': 'string',
                'description': 'Original PDF filename'
            }
        },
        'required': ['invoice_data']
    }
}
```

**Add method:**

```python
def _create_vendor_bill_from_pdf(self, invoice_data: Dict,
                                  pdf_content: str = None,
                                  filename: str = None) -> Dict:
    """Create vendor bill from parsed PDF data"""
    try:
        # Find or create vendor
        Partner = self.env['res.partner']
        vendor = Partner.search([
            '|',
            ('name', 'ilike', invoice_data.get('vendor_name', '')),
            ('vat', '=', invoice_data.get('vendor_vat', ''))
        ], limit=1)

        if not vendor:
            # Create new vendor
            vendor = Partner.create({
                'name': invoice_data['vendor_name'],
                'vat': invoice_data.get('vendor_vat'),
                'supplier_rank': 1
            })

        # Create invoice
        Invoice = self.env['account.move']

        invoice_lines = []
        for line_data in invoice_data.get('lines', []):
            # Find or create product
            Product = self.env['product.product']
            product = Product.search([
                ('name', 'ilike', line_data['description'])
            ], limit=1)

            if not product:
                # Use default expense product or create
                product = Product.search([('default_code', '=', 'EXP')], limit=1)
                if not product:
                    product = Product.create({
                        'name': line_data['description'][:50],
                        'type': 'service',
                        'default_code': 'EXP'
                    })

            invoice_lines.append((0, 0, {
                'product_id': product.id,
                'name': line_data['description'],
                'quantity': line_data.get('quantity', 1.0),
                'price_unit': line_data.get('unit_price', 0.0),
            }))

        invoice_vals = {
            'partner_id': vendor.id,
            'move_type': 'in_invoice',
            'invoice_date': invoice_data.get('invoice_date'),
            'invoice_date_due': invoice_data.get('due_date'),
            'ref': invoice_data.get('invoice_number'),
            'invoice_line_ids': invoice_lines,
        }

        invoice = Invoice.create(invoice_vals)

        # Attach PDF if provided
        if pdf_content and filename:
            Attachment = self.env['ir.attachment']
            Attachment.create({
                'name': filename,
                'datas': pdf_content,  # Already base64 encoded
                'res_model': 'account.move',
                'res_id': invoice.id,
                'mimetype': 'application/pdf'
            })

        return {
            'success': True,
            'invoice_id': invoice.id,
            'invoice_number': invoice.name,
            'vendor': vendor.name,
            'total': invoice.amount_total,
            'message': f'Successfully created vendor bill {invoice.name} for {vendor.name}'
        }

    except Exception as e:
        _logger.exception("Error creating vendor bill from PDF")
        return {
            'success': False,
            'error': str(e)
        }
```

#### 5. Create Upload Endpoint

**File:** `odoo_ai_chat/controllers/main.py`

Add route:

```python
@http.route('/ai_chat/upload_pdf', type='http', auth='user', methods=['POST'], csrf=False)
def upload_pdf(self, **kwargs):
    """Handle PDF file upload"""
    try:
        file = request.httprequest.files.get('file')
        session_id = request.params.get('session_id')

        if not file:
            return request.make_json_response({
                'success': False,
                'error': 'No file provided'
            })

        # Read file content
        pdf_content = file.read()
        filename = file.filename

        # Process PDF
        from ..models.pdf_processor import PDFInvoiceProcessor
        processor = PDFInvoiceProcessor(request.env)
        result = processor.process_pdf(pdf_content, filename)

        if result['success']:
            # Store in session or temporary storage
            # You might want to store this in ir.attachment temporarily
            Attachment = request.env['ir.attachment']
            attachment = Attachment.create({
                'name': filename,
                'datas': base64.b64encode(pdf_content).decode('utf-8'),
                'res_model': 'ai.chat.session',
                'res_id': int(session_id) if session_id else False,
                'mimetype': 'application/pdf'
            })

            return request.make_json_response({
                'success': True,
                'attachment_id': attachment.id,
                'filename': filename,
                'data': result['data']
            })
        else:
            return request.make_json_response(result)

    except Exception as e:
        _logger.exception("Error uploading PDF")
        return request.make_json_response({
            'success': False,
            'error': str(e)
        })
```

---

## Summary

### For Graphs:
1. Add `generate_graph` MCP tool
2. Install pandas (and optionally matplotlib)
3. Add Chart.js to frontend
4. Create chart renderer component
5. Update templates to display graphs

### For PDF Invoices:
1. Add file upload UI component
2. Install PDF processing libraries (pdfplumber, pytesseract)
3. Create PDF processor class
4. Add `create_vendor_bill_from_pdf` MCP tool
5. Create upload endpoint
6. Use AI to parse extracted text into structured data

### Additional Considerations:

**For Production:**
- Consider using cloud OCR services for better accuracy
- Add file size limits and validation
- Implement rate limiting for uploads
- Add progress indicators for long operations
- Cache processed results
- Add user confirmation before creating records

**For Both Features:**
- Add appropriate error handling
- Update security access rights
- Add logging and monitoring
- Create unit tests
- Update user documentation

Would you like me to implement either of these features now, or do you have questions about the approach?
