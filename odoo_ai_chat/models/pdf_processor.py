"""PDF Invoice Processing"""

import logging
import base64
import json
import io
from typing import Dict, Optional

from odoo import exceptions

_logger = logging.getLogger(__name__)

# Use PyPDF2 (lightweight, pure Python, already available in Odoo)
try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    _logger.warning("PyPDF2 not available. PDF processing will be disabled.")

# Use PyMuPDF for OCR support (convert PDF pages to images)
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    _logger.warning("PyMuPDF not available. OCR for scanned PDFs will be disabled.")


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
        if not PYPDF2_AVAILABLE:
            return {
                'success': False,
                'error': 'PDF processing library not available. PyPDF2 is required but not found.'
            }

        try:
            # Extract text from PDF
            text = self._extract_text(pdf_content)

            # Log what we extracted for debugging
            text_length = len(text.strip()) if text else 0
            _logger.info(f"Extracted {text_length} characters from PDF: {filename}")
            if text:
                _logger.info(f"First 200 chars: {text[:200]}")

            if not text or text_length < 50:
                # Try OCR for scanned/image-based PDFs
                _logger.info("Text extraction failed, attempting OCR...")

                if not PYMUPDF_AVAILABLE:
                    return {
                        'success': False,
                        'error': f'Could not extract sufficient text from PDF ({text_length} characters found). This PDF appears to be scanned/image-based. OCR is not available (PyMuPDF not installed). Please install PyMuPDF: pip install PyMuPDF'
                    }

                try:
                    text = self._extract_text_with_ocr(pdf_content, filename)
                    text_length = len(text.strip()) if text else 0
                    _logger.info(f"OCR extracted {text_length} characters from PDF")

                    if not text or text_length < 50:
                        return {
                            'success': False,
                            'error': f'OCR could not extract sufficient text from PDF ({text_length} characters found). The PDF may be empty, corrupted, or have very low quality images.'
                        }
                except Exception as e:
                    _logger.exception("OCR extraction failed")
                    return {
                        'success': False,
                        'error': f'OCR processing failed: {str(e)}'
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
        """Extract text from PDF using PyPDF2 (lightweight alternative)"""
        text_parts = []

        try:
            pdf_file = io.BytesIO(pdf_content)

            # Support both old and new PyPDF2 API
            try:
                # Try new API (PyPDF2 >= 3.0)
                pdf_reader = PyPDF2.PdfReader(pdf_file)
            except AttributeError:
                # Fall back to old API (PyPDF2 < 3.0)
                pdf_reader = PyPDF2.PdfFileReader(pdf_file)

            # Handle pages differently for old/new API
            try:
                # New API
                num_pages = len(pdf_reader.pages)
                pages = pdf_reader.pages
            except AttributeError:
                # Old API
                num_pages = pdf_reader.numPages
                pages = [pdf_reader.getPage(i) for i in range(num_pages)]

            _logger.info(f"Processing PDF with {num_pages} pages")

            for page_num, page in enumerate(pages, 1):
                _logger.info(f"Extracting text from page {page_num}")

                # Extract text from page (both APIs use extractText or extract_text)
                try:
                    text = page.extract_text()  # New API
                except AttributeError:
                    text = page.extractText()  # Old API

                if text and text.strip():
                    text_parts.append(text)

            extracted_text = '\n'.join(text_parts)

            # Note: PyPDF2 doesn't extract tables as structured data like pdfplumber
            # But the AI can still parse invoice data from the raw text
            return extracted_text

        except Exception as e:
            _logger.exception("Error extracting text from PDF")
            raise

    def _extract_text_with_ocr(self, pdf_content: bytes, filename: str) -> str:
        """
        Extract text from scanned PDF using OCR via vision AI models

        Process:
        1. Convert PDF pages to images using PyMuPDF
        2. Send images to OpenRouter vision model (GPT-4 Vision, Claude Vision, etc.)
        3. Extract text from images using vision model

        Args:
            pdf_content: PDF file content as bytes
            filename: Original filename for logging

        Returns:
            Extracted text from all pages
        """
        if not PYMUPDF_AVAILABLE:
            raise exceptions.UserError("PyMuPDF not installed. Cannot perform OCR.")

        try:
            # Open PDF with PyMuPDF
            pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
            num_pages = len(pdf_document)

            _logger.info(f"Converting {num_pages} PDF pages to images for OCR")

            # Convert PDF pages to images
            page_images = []
            for page_num in range(num_pages):
                page = pdf_document[page_num]

                # Render page to image (PNG format, 300 DPI for good OCR quality)
                pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))

                # Convert to bytes
                img_bytes = pix.tobytes("png")

                # Convert to base64
                img_b64 = base64.b64encode(img_bytes).decode('utf-8')

                page_images.append({
                    'page_num': page_num + 1,
                    'image_b64': img_b64,
                    'format': 'png'
                })

                _logger.info(f"Converted page {page_num + 1} to image ({len(img_bytes)} bytes)")

            pdf_document.close()

            # Use vision AI model to extract text from images
            extracted_text = self._ocr_with_vision_model(page_images, filename)

            return extracted_text

        except Exception as e:
            _logger.exception("Error during OCR extraction")
            raise

    def _ocr_with_vision_model(self, page_images: list, filename: str) -> str:
        """
        Use OpenRouter vision model to extract text from PDF page images

        Args:
            page_images: List of dicts with page_num, image_b64, format
            filename: Original filename for context

        Returns:
            Extracted text from all pages
        """
        # Get AI config
        config = self.env['res.config.settings'].get_ai_config()

        if not config.get('api_key'):
            raise exceptions.UserError("OpenRouter API key not configured")

        from .ai_provider import OpenRouterProvider

        # Use a vision-capable model
        # Priority: GPT-4 Vision > Claude 3 Opus > Claude 3 Sonnet
        vision_model = self._get_vision_model(config.get('model'))

        ai_provider = OpenRouterProvider(
            api_key=config['api_key'],
            model=vision_model,
            site_url=config['site_url'],
            site_name=config['site_name']
        )

        all_text = []

        for page_data in page_images:
            page_num = page_data['page_num']
            image_b64 = page_data['image_b64']

            _logger.info(f"Performing OCR on page {page_num} using vision model {vision_model}")

            # Create message with image
            messages = [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'text',
                            'text': 'Extract ALL text from this image. Return only the extracted text, no additional comments or formatting. Preserve the layout and structure as much as possible.'
                        },
                        {
                            'type': 'image_url',
                            'image_url': {
                                'url': f'data:image/png;base64,{image_b64}'
                            }
                        }
                    ]
                }
            ]

            try:
                response = ai_provider.chat(messages=messages, temperature=0.0, max_tokens=4000)
                page_text = response.get('choices', [{}])[0].get('message', {}).get('content', '')

                if page_text:
                    all_text.append(f"--- Page {page_num} ---\n{page_text}\n")
                    _logger.info(f"Extracted {len(page_text)} characters from page {page_num}")

            except Exception as e:
                _logger.error(f"OCR failed for page {page_num}: {str(e)}")
                # Continue with other pages even if one fails
                continue

        return '\n'.join(all_text)

    def _get_vision_model(self, current_model: str) -> str:
        """
        Get appropriate vision model for OCR

        If current model supports vision, use it.
        Otherwise, fall back to a known vision-capable model.
        """
        # List of known vision-capable models
        vision_models = [
            'openai/gpt-4-turbo',
            'openai/gpt-4o',
            'openai/gpt-4-vision-preview',
            'anthropic/claude-3-opus',
            'anthropic/claude-3-sonnet',
            'anthropic/claude-3.5-sonnet',
            'anthropic/claude-3-haiku',
        ]

        # Check if current model is vision-capable
        if any(vm in current_model for vm in ['gpt-4', 'claude-3', 'vision']):
            _logger.info(f"Using current model for OCR: {current_model}")
            return current_model

        # Fall back to GPT-4 Turbo (widely available, good OCR)
        fallback_model = 'openai/gpt-4o'
        _logger.info(f"Current model {current_model} may not support vision. Using fallback: {fallback_model}")
        return fallback_model

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
