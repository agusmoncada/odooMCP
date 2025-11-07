"""PDF Invoice Processing"""

import logging
import base64
import json
import io
from typing import Dict, Optional

from odoo import exceptions

_logger = logging.getLogger(__name__)

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    _logger.warning("pdfplumber not available. Install with: pip3 install pdfplumber")


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
                'error': 'PDF processing library not available. Install with: pip3 install pdfplumber'
            }

        try:
            # Extract text from PDF
            text = self._extract_text(pdf_content)

            if not text or len(text.strip()) < 50:
                return {
                    'success': False,
                    'error': 'Could not extract sufficient text from PDF. The PDF might be image-based or empty.'
                }

            # Use AI to parse the invoice text
            invoice_data = self._parse_with_ai(text, filename)

            return {
                'success': True,
                'data': invoice_data,
                'raw_text': text[:1000],  # First 1000 chars for reference
                'filename': filename
            }

        except Exception as e:
            _logger.exception("Error processing PDF")
            return {
                'success': False,
                'error': str(e)
            }

    def _extract_text(self, pdf_content: bytes) -> str:
        """Extract text from PDF using pdfplumber"""
        text_parts = []

        try:
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    _logger.info(f"Extracting text from page {page_num}")

                    # Try to extract text
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)

                    # Also try to extract tables
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            # Convert table to text representation
                            for row in table:
                                if row:
                                    text_parts.append(" | ".join(str(cell) if cell else "" for cell in row))

            return '\n'.join(text_parts)

        except Exception as e:
            _logger.exception("Error extracting text from PDF")
            raise

    def _parse_with_ai(self, text: str, filename: str) -> Dict:
        """
        Use AI to parse invoice text and extract structured data

        This method:
        1. Sends the text to OpenRouter with a specialized prompt
        2. Requests structured JSON output
        3. Returns parsed invoice data
        """
        # Get AI config
        config = self.env['res.config.settings'].get_ai_config()

        if not config.get('api_key'):
            raise exceptions.UserError("OpenRouter API key not configured")

        from .ai_provider import OpenRouterProvider

        ai_provider = OpenRouterProvider(
            api_key=config['api_key'],
            model=config['model'],
            site_url=config['site_url'],
            site_name=config['site_name']
        )

        # Specialized prompt for invoice extraction
        prompt = f"""Extract invoice information from the following text and return ONLY a valid JSON object with this exact structure:

{{
    "vendor_name": "Company name of the vendor/supplier",
    "vendor_vat": "Tax ID/VAT number if available, otherwise null",
    "vendor_email": "Email if available, otherwise null",
    "vendor_phone": "Phone if available, otherwise null",
    "invoice_number": "Invoice reference number",
    "invoice_date": "Date in YYYY-MM-DD format",
    "due_date": "Due date in YYYY-MM-DD format if available, otherwise null",
    "currency": "Currency code (USD, EUR, etc.), default to USD if not found",
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
    "notes": "Any additional notes, payment terms, or special instructions"
}}

IMPORTANT RULES:
- Return ONLY the JSON object, no markdown, no explanations
- All numeric values must be numbers, not strings
- All dates must be in YYYY-MM-DD format
- Use null for missing values, not empty strings
- Ensure the JSON is valid and parseable
- Calculate subtotals correctly: quantity * unit_price
- Ensure total = subtotal + tax_total

Invoice text:
{text}
"""

        messages = [
            {
                'role': 'system',
                'content': 'You are an expert at extracting structured data from invoices. You always respond with valid JSON only, no additional text or formatting.'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ]

        try:
            response = ai_provider.chat(messages=messages, temperature=0.1, max_tokens=2000)

            # Extract and parse JSON from response
            ai_text = response.get('choices', [{}])[0].get('message', {}).get('content', '')

            _logger.info(f"AI response for invoice parsing: {ai_text[:500]}")

            # Try to parse JSON
            invoice_data = self._extract_json_from_text(ai_text)

            # Validate required fields
            if not invoice_data.get('vendor_name'):
                raise ValueError("Could not extract vendor name from invoice")

            if not invoice_data.get('invoice_number'):
                raise ValueError("Could not extract invoice number")

            if not invoice_data.get('lines') or len(invoice_data['lines']) == 0:
                raise ValueError("Could not extract any line items from invoice")

            return invoice_data

        except Exception as e:
            _logger.exception("Error parsing invoice with AI")
            raise exceptions.UserError(f"Failed to parse invoice: {str(e)}")

    def _extract_json_from_text(self, text: str) -> Dict:
        """Extract JSON from AI response text"""
        # Remove markdown code blocks if present
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0].strip()
        elif '```' in text:
            text = text.split('```')[1].split('```')[0].strip()

        # Try to find JSON object
        start_idx = text.find('{')
        end_idx = text.rfind('}')

        if start_idx == -1 or end_idx == -1:
            raise ValueError("No JSON object found in response")

        json_text = text[start_idx:end_idx + 1]

        try:
            return json.loads(json_text)
        except json.JSONDecodeError as e:
            _logger.error(f"Failed to parse JSON: {json_text}")
            raise ValueError(f"Invalid JSON in response: {str(e)}")

    def create_vendor_bill(self, invoice_data: Dict, pdf_content_b64: str = None,
                          filename: str = None) -> Dict:
        """
        Create vendor bill from parsed PDF data

        Args:
            invoice_data: Parsed invoice data dict
            pdf_content_b64: Base64 encoded PDF content
            filename: Original filename

        Returns:
            Dict with invoice creation result
        """
        try:
            # Find or create vendor
            vendor = self._find_or_create_vendor(invoice_data)

            # Create invoice lines
            invoice_lines = self._create_invoice_lines(invoice_data)

            # Create invoice
            Invoice = self.env['account.move']

            invoice_vals = {
                'partner_id': vendor.id,
                'move_type': 'in_invoice',
                'invoice_date': invoice_data.get('invoice_date'),
                'invoice_date_due': invoice_data.get('due_date'),
                'ref': invoice_data.get('invoice_number'),
                'invoice_line_ids': invoice_lines,
                'narration': invoice_data.get('notes'),
            }

            # Set currency if provided
            if invoice_data.get('currency'):
                Currency = self.env['res.currency']
                currency = Currency.search([('name', '=', invoice_data['currency'])], limit=1)
                if currency:
                    invoice_vals['currency_id'] = currency.id

            invoice = Invoice.create(invoice_vals)

            # Attach PDF if provided
            if pdf_content_b64 and filename:
                self._attach_pdf_to_invoice(invoice, pdf_content_b64, filename)

            _logger.info(f"Created vendor bill {invoice.name} for {vendor.name}")

            return {
                'success': True,
                'invoice_id': invoice.id,
                'invoice_name': invoice.name,
                'vendor_name': vendor.name,
                'total': invoice.amount_total,
                'currency': invoice.currency_id.name,
                'message': f'Successfully created vendor bill {invoice.name} for {vendor.name}'
            }

        except Exception as e:
            _logger.exception("Error creating vendor bill from PDF")
            return {
                'success': False,
                'error': str(e)
            }

    def _find_or_create_vendor(self, invoice_data: Dict):
        """Find existing vendor or create new one"""
        Partner = self.env['res.partner']

        vendor_name = invoice_data.get('vendor_name', '').strip()
        vendor_vat = invoice_data.get('vendor_vat', '').strip() if invoice_data.get('vendor_vat') else None

        # Search for existing vendor
        domain = []
        if vendor_vat:
            domain = ['|', ('name', 'ilike', vendor_name), ('vat', '=', vendor_vat)]
        else:
            domain = [('name', 'ilike', vendor_name)]

        vendor = Partner.search(domain, limit=1)

        if not vendor:
            # Create new vendor
            vendor_vals = {
                'name': vendor_name,
                'supplier_rank': 1,
                'is_company': True,
            }

            if vendor_vat:
                vendor_vals['vat'] = vendor_vat

            if invoice_data.get('vendor_email'):
                vendor_vals['email'] = invoice_data['vendor_email']

            if invoice_data.get('vendor_phone'):
                vendor_vals['phone'] = invoice_data['vendor_phone']

            vendor = Partner.create(vendor_vals)
            _logger.info(f"Created new vendor: {vendor.name}")
        else:
            _logger.info(f"Found existing vendor: {vendor.name}")

        return vendor

    def _create_invoice_lines(self, invoice_data: Dict):
        """Create invoice lines from parsed data"""
        Product = self.env['product.product']
        invoice_lines = []

        for line_data in invoice_data.get('lines', []):
            description = line_data.get('description', '').strip()

            if not description:
                continue

            # Try to find matching product
            product = Product.search([
                ('name', 'ilike', description)
            ], limit=1)

            # If not found, look for generic expense product
            if not product:
                product = Product.search([
                    '|',
                    ('default_code', '=', 'EXP'),
                    ('name', '=', 'Generic Expense')
                ], limit=1)

            # Create line values
            line_vals = {
                'name': description,
                'quantity': float(line_data.get('quantity', 1.0)),
                'price_unit': float(line_data.get('unit_price', 0.0)),
            }

            if product:
                line_vals['product_id'] = product.id

            invoice_lines.append((0, 0, line_vals))

        return invoice_lines

    def _attach_pdf_to_invoice(self, invoice, pdf_content_b64: str, filename: str):
        """Attach PDF file to invoice"""
        Attachment = self.env['ir.attachment']

        Attachment.create({
            'name': filename,
            'datas': pdf_content_b64,
            'res_model': 'account.move',
            'res_id': invoice.id,
            'mimetype': 'application/pdf',
            'description': 'Original invoice PDF'
        })

        _logger.info(f"Attached PDF {filename} to invoice {invoice.name}")
