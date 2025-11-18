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

# OCR capabilities using Tesseract and pdf2image
try:
    import pytesseract
    from pdf2image import convert_from_bytes
    from PIL import Image
    OCR_AVAILABLE = True
    _logger.info("OCR capabilities available (pytesseract + pdf2image)")
except ImportError as e:
    OCR_AVAILABLE = False
    _logger.warning(f"OCR not available: {e}. To enable OCR for scanned PDFs, install: pip install pytesseract pdf2image pillow")


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
            # Extract text from PDF using PyPDF2
            text = self._extract_text(pdf_content)

            # Log what we extracted for debugging
            text_length = len(text.strip()) if text else 0
            _logger.info(f"Extracted {text_length} characters from PDF: {filename}")
            if text:
                _logger.info(f"First 200 chars: {text[:200]}")

            # If insufficient text extracted, try OCR (traditional first, AI as fallback)
            if not text or text_length < 50:
                _logger.info(f"Insufficient text from PyPDF2 ({text_length} chars), attempting OCR...")
                
                # First try traditional OCR (free)
                if OCR_AVAILABLE:
                    ocr_text = self._extract_text_ocr(pdf_content)
                    if ocr_text:
                        ocr_length = len(ocr_text.strip())
                        _logger.info(f"Traditional OCR extracted {ocr_length} characters")
                        if ocr_length > 50:  # Good enough text found
                            text = ocr_text
                            text_length = ocr_length
                            _logger.info("Using traditional OCR text")
                        else:
                            _logger.info("Traditional OCR didn't extract enough text, trying AI OCR...")
                            # Try AI-based OCR as fallback (costs money but more accurate)
                            ai_ocr_text = self._extract_text_ai_ocr(pdf_content)
                            if ai_ocr_text and len(ai_ocr_text.strip()) > ocr_length:
                                text = ai_ocr_text
                                text_length = len(ai_ocr_text.strip())
                                _logger.info("Using AI OCR text (premium)")
                else:
                    _logger.info("Traditional OCR not available, trying AI OCR...")
                    # No traditional OCR available, try AI directly
                    ai_ocr_text = self._extract_text_ai_ocr(pdf_content)
                    if ai_ocr_text:
                        text = ai_ocr_text
                        text_length = len(ai_ocr_text.strip())
                        _logger.info("Using AI OCR text (premium)")

            # Final check for sufficient text
            if not text or text_length < 50:
                error_msg = f'Could not extract sufficient text from PDF ({text_length} characters found). This PDF appears to be scanned/image-based.'
                if not OCR_AVAILABLE:
                    error_msg += ' OCR is not available. To enable OCR for scanned PDFs, install: pip install pytesseract pdf2image pillow'
                else:
                    error_msg += ' OCR was attempted but failed to extract readable text.'
                
                return {
                    'success': False,
                    'error': error_msg
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

    def _extract_text_ocr(self, pdf_content: bytes) -> str:
        """Extract text from PDF using OCR (for scanned/image-based PDFs)"""
        if not OCR_AVAILABLE:
            return ""
        
        try:
            _logger.info("Converting PDF to images for OCR processing...")
            
            # Convert PDF to images
            images = convert_from_bytes(pdf_content, dpi=300)  # High DPI for better OCR accuracy
            _logger.info(f"Converted PDF to {len(images)} images")
            
            text_parts = []
            
            for page_num, image in enumerate(images, 1):
                _logger.info(f"OCR processing page {page_num}...")
                
                # Configure Tesseract for better invoice recognition
                custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,@#$%()-:/ '
                
                # Extract text using Tesseract
                try:
                    page_text = pytesseract.image_to_string(image, config=custom_config)
                    
                    if page_text and page_text.strip():
                        text_parts.append(page_text.strip())
                        _logger.info(f"OCR page {page_num}: extracted {len(page_text)} characters")
                    
                except Exception as e:
                    _logger.warning(f"OCR failed on page {page_num}: {e}")
                    continue
            
            ocr_text = '\n'.join(text_parts)
            _logger.info(f"Total OCR text length: {len(ocr_text)} characters")
            
            return ocr_text
            
        except Exception as e:
            _logger.exception("Error during OCR processing")
            return ""

    def _extract_text_ai_ocr(self, pdf_content: bytes) -> str:
        """Extract text using AI vision models (premium but highly accurate)"""
        try:
            _logger.info("Attempting AI-based OCR using vision model...")
            
            # Convert PDF to high-quality images
            if not OCR_AVAILABLE:
                _logger.warning("pdf2image not available for AI OCR")
                return ""
            
            from pdf2image import convert_from_bytes
            images = convert_from_bytes(pdf_content, dpi=200)  # Lower DPI for AI (faster)
            
            if not images:
                return ""
            
            # Use only first 3 pages to control costs
            pages_to_process = min(3, len(images))
            _logger.info(f"Processing first {pages_to_process} pages with AI OCR")
            
            text_parts = []
            
            for page_num in range(pages_to_process):
                try:
                    image = images[page_num]
                    
                    # Convert PIL Image to base64 for AI
                    import io
                    import base64
                    buffer = io.BytesIO()
                    image.save(buffer, format='PNG')
                    image_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    
                    # Get AI config for vision
                    config = self.env['res.config.settings'].get_ai_config()
                    if not config.get('api_key'):
                        _logger.warning("No AI API key configured for AI OCR")
                        return ""
                    
                    from .ai_provider import OpenRouterProvider
                    ai_provider = OpenRouterProvider(
                        api_key=config['api_key'],
                        model="anthropic/claude-3-haiku",  # Good for vision, cost-effective
                        site_url=config['site_url'],
                        site_name=config['site_name']
                    )
                    
                    # Vision prompt for OCR
                    messages = [
                        {
                            'role': 'user',
                            'content': [
                                {
                                    'type': 'text',
                                    'text': 'Extract all text from this image precisely. Return only the raw text, no formatting or explanations. Pay special attention to invoice numbers, dates, company names, amounts, and line items.'
                                },
                                {
                                    'type': 'image',
                                    'source': {
                                        'type': 'base64',
                                        'media_type': 'image/png',
                                        'data': image_b64
                                    }
                                }
                            ]
                        }
                    ]
                    
                    response = ai_provider.chat(messages=messages, temperature=0.0, max_tokens=2000)
                    page_text = response.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
                    
                    if page_text:
                        text_parts.append(page_text)
                        _logger.info(f"AI OCR page {page_num + 1}: extracted {len(page_text)} characters")
                    
                except Exception as e:
                    _logger.warning(f"AI OCR failed on page {page_num + 1}: {e}")
                    continue
            
            ai_text = '\n'.join(text_parts)
            _logger.info(f"AI OCR total: {len(ai_text)} characters extracted")
            
            return ai_text
            
        except Exception as e:
            _logger.exception("Error during AI OCR processing")
            return ""

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

            # Create activity reminder for review
            self._create_review_activity(invoice, vendor)

            _logger.info(f"Created vendor bill {invoice.name} for {vendor.name} with review activity")

            return {
                'success': True,
                'invoice_id': invoice.id,
                'invoice_name': invoice.name,
                'vendor_name': vendor.name,
                'total': invoice.amount_total,
                'currency': invoice.currency_id.name,
                'message': f'Successfully created vendor bill {invoice.name} for {vendor.name}. Review activity has been scheduled.'
            }

        except Exception as e:
            _logger.exception("Error creating vendor bill from PDF")
            return {
                'success': False,
                'error': str(e)
            }

    def _find_or_create_vendor(self, invoice_data: Dict):
        """Find existing vendor or create new one with enhanced search"""
        Partner = self.env['res.partner']

        vendor_name = invoice_data.get('vendor_name', '').strip()
        vendor_vat = invoice_data.get('vendor_vat', '').strip() if invoice_data.get('vendor_vat') else None
        vendor_email = invoice_data.get('vendor_email', '').strip() if invoice_data.get('vendor_email') else None

        _logger.info(f"Searching for vendor: name='{vendor_name}', vat='{vendor_vat}', email='{vendor_email}'")

        # Enhanced search strategy
        vendor = None
        
        # 1. First try exact VAT match (most reliable)
        if vendor_vat:
            vendor = Partner.search([
                ('vat', '=', vendor_vat),
                ('supplier_rank', '>', 0)  # Only suppliers
            ], limit=1)
            if vendor:
                _logger.info(f"Found vendor by VAT: {vendor.name}")
                return vendor

        # 2. Try email match (also quite reliable)
        if vendor_email:
            vendor = Partner.search([
                ('email', '=', vendor_email),
                ('supplier_rank', '>', 0)
            ], limit=1)
            if vendor:
                _logger.info(f"Found vendor by email: {vendor.name}")
                return vendor

        # 3. Try exact name match
        vendor = Partner.search([
            ('name', '=', vendor_name),
            ('supplier_rank', '>', 0)
        ], limit=1)
        if vendor:
            _logger.info(f"Found vendor by exact name: {vendor.name}")
            return vendor

        # 4. Try fuzzy name match with different variations
        name_variations = [
            vendor_name,
            vendor_name.upper(),
            vendor_name.lower(),
            vendor_name.title(),
        ]
        
        for name_var in name_variations:
            vendor = Partner.search([
                ('name', 'ilike', name_var),
                ('supplier_rank', '>', 0)
            ], limit=1)
            if vendor:
                _logger.info(f"Found vendor by fuzzy name match: {vendor.name} (matched '{name_var}')")
                return vendor

        # 5. No vendor found - create new one
        _logger.info(f"No existing vendor found. Creating new vendor: {vendor_name}")
        
        vendor_vals = {
            'name': vendor_name,
            'supplier_rank': 1,
            'customer_rank': 0,  # Not a customer by default
            'is_company': True,
            'category_id': [(6, 0, [])],  # Empty categories initially
        }

        if vendor_vat:
            vendor_vals['vat'] = vendor_vat

        if vendor_email:
            vendor_vals['email'] = vendor_email

        if invoice_data.get('vendor_phone'):
            vendor_vals['phone'] = invoice_data['vendor_phone']

        # Add default supplier category if available
        SupplierCategory = self.env['res.partner.category']
        supplier_cat = SupplierCategory.search([('name', 'ilike', 'supplier')], limit=1)
        if supplier_cat:
            vendor_vals['category_id'] = [(6, 0, [supplier_cat.id])]

        vendor = Partner.create(vendor_vals)
        _logger.info(f"Created new vendor: {vendor.name} (ID: {vendor.id})")
        
        return vendor

    def _create_invoice_lines(self, invoice_data: Dict):
        """Create invoice lines from parsed data with automatic product creation"""
        Product = self.env['product.product']
        ProductCategory = self.env['product.category']
        invoice_lines = []

        for line_data in invoice_data.get('lines', []):
            description = line_data.get('description', '').strip()

            if not description:
                continue

            _logger.info(f"Processing line item: {description}")

            # Enhanced product search
            product = self._find_or_create_product(description)

            # Create line values
            line_vals = {
                'name': description,
                'quantity': float(line_data.get('quantity', 1.0)),
                'price_unit': float(line_data.get('unit_price', 0.0)),
            }

            if product:
                line_vals['product_id'] = product.id
                # Update product purchase price if we have a better one
                if line_vals['price_unit'] > 0:
                    if not product.standard_price or product.standard_price == 0:
                        product.standard_price = line_vals['price_unit']
                        _logger.info(f"Updated product {product.name} cost price to {line_vals['price_unit']}")

            invoice_lines.append((0, 0, line_vals))

        return invoice_lines

    def _find_or_create_product(self, description: str):
        """Find existing product or create new one based on description"""
        Product = self.env['product.product']
        ProductCategory = self.env['product.category']
        
        # 1. Try exact name match
        product = Product.search([('name', '=', description)], limit=1)
        if product:
            _logger.info(f"Found product by exact name: {product.name}")
            return product

        # 2. Try fuzzy search with variations
        search_terms = [
            description,
            description.lower(),
            description.title(),
            description.upper(),
        ]
        
        for term in search_terms:
            # Search by name
            product = Product.search([('name', 'ilike', term)], limit=1)
            if product:
                _logger.info(f"Found product by fuzzy name: {product.name} (searched: {term})")
                return product
                
            # Search by default_code (internal reference)
            product = Product.search([('default_code', 'ilike', term)], limit=1)
            if product:
                _logger.info(f"Found product by reference: {product.name} (searched: {term})")
                return product

        # 3. Look for generic expense/service product as fallback
        fallback_products = Product.search([
            '|', '|', '|',
            ('default_code', '=', 'EXP'),
            ('name', '=', 'Generic Expense'),
            ('name', '=', 'Miscellaneous'),
            ('name', 'ilike', 'expense')
        ], limit=1)
        
        if fallback_products:
            _logger.info(f"Using fallback product: {fallback_products[0].name}")
            return fallback_products[0]

        # 4. Create new product
        _logger.info(f"Creating new product: {description}")
        
        # Determine category based on keywords
        category_name = self._guess_product_category(description)
        category = ProductCategory.search([('name', 'ilike', category_name)], limit=1)
        
        if not category:
            # Create category if it doesn't exist
            category = ProductCategory.create({
                'name': category_name,
                'parent_id': False,
            })
            _logger.info(f"Created new category: {category_name}")

        # Create product
        product_vals = {
            'name': description,
            'type': 'service',  # Default to service for invoice items
            'purchase_ok': True,
            'sale_ok': False,  # Usually vendor bill items are not for resale
            'categ_id': category.id if category else False,
            'default_code': self._generate_product_code(description),
        }

        try:
            product = Product.create(product_vals)
            _logger.info(f"Created new product: {product.name} (ID: {product.id}) in category: {category_name}")
            return product
        except Exception as e:
            _logger.warning(f"Failed to create product '{description}': {e}")
            return False

    def _guess_product_category(self, description: str) -> str:
        """Guess product category based on description keywords"""
        description_lower = description.lower()
        
        # Define keyword mappings
        category_keywords = {
            'Office Supplies': ['paper', 'pen', 'pencil', 'office', 'supplies', 'stationery', 'folder'],
            'Software & IT': ['software', 'license', 'subscription', 'hosting', 'domain', 'cloud', 'saas'],
            'Marketing': ['marketing', 'advertising', 'promotion', 'design', 'campaign', 'social media'],
            'Travel & Transport': ['travel', 'flight', 'hotel', 'taxi', 'transport', 'fuel', 'mileage'],
            'Professional Services': ['consulting', 'legal', 'accounting', 'professional', 'service', 'advisory'],
            'Utilities': ['electricity', 'water', 'gas', 'internet', 'phone', 'utility', 'telecom'],
            'Maintenance': ['repair', 'maintenance', 'cleaning', 'service', 'fix'],
            'Equipment': ['equipment', 'hardware', 'machine', 'tool', 'device'],
            'Food & Beverages': ['food', 'coffee', 'lunch', 'catering', 'beverage', 'meal'],
        }
        
        for category, keywords in category_keywords.items():
            if any(keyword in description_lower for keyword in keywords):
                return category
        
        # Default category
        return 'General Expenses'

    def _generate_product_code(self, description: str) -> str:
        """Generate a product code from description"""
        # Take first 3 words, first 2 letters each, uppercase
        words = description.split()[:3]
        code_parts = []
        
        for word in words:
            clean_word = ''.join(c for c in word if c.isalnum())
            if clean_word:
                code_parts.append(clean_word[:2].upper())
        
        if not code_parts:
            code_parts = ['GE']  # Generic Expense
            
        base_code = ''.join(code_parts)
        
        # Ensure uniqueness
        Product = self.env['product.product']
        counter = 1
        final_code = base_code
        
        while Product.search([('default_code', '=', final_code)], limit=1):
            final_code = f"{base_code}{counter:02d}"
            counter += 1
        
        return final_code

    def _create_review_activity(self, invoice, vendor):
        """Create an activity reminder to review the auto-created invoice"""
        try:
            Activity = self.env['mail.activity']
            ActivityType = self.env['mail.activity.type']
            
            # Find or create "To Do" activity type
            todo_type = ActivityType.search([
                '|',
                ('name', '=', 'To Do'),
                ('name', 'ilike', 'todo')
            ], limit=1)
            
            if not todo_type:
                # Try other common activity types
                todo_type = ActivityType.search([
                    '|', '|',
                    ('name', 'ilike', 'review'),
                    ('name', 'ilike', 'follow'),
                    ('name', 'ilike', 'call')
                ], limit=1)
            
            if not todo_type:
                _logger.warning("No suitable activity type found, skipping activity creation")
                return
            
            # Calculate due date (1 day from now)
            from datetime import date, timedelta
            due_date = date.today() + timedelta(days=1)
            
            # Create activity
            activity_vals = {
                'activity_type_id': todo_type.id,
                'summary': f'Review Auto-Generated Invoice: {invoice.name}',
                'note': f'''<p><strong>Auto-generated invoice requires review:</strong></p>
<ul>
<li><strong>Vendor:</strong> {vendor.name}</li>
<li><strong>Invoice:</strong> {invoice.name}</li>
<li><strong>Amount:</strong> {invoice.currency_id.symbol}{invoice.amount_total:,.2f}</li>
<li><strong>Reference:</strong> {invoice.ref or 'N/A'}</li>
</ul>
<p><strong>Please verify:</strong></p>
<ul>
<li>✅ Vendor details are correct</li>
<li>✅ Line items and amounts are accurate</li>
<li>✅ GL accounts are properly assigned</li>
<li>✅ Tax calculations are correct</li>
</ul>
<p><em>This invoice was automatically created from PDF using AI extraction.</em></p>''',
                'res_id': invoice.id,
                'res_model': 'account.move',
                'user_id': self.env.user.id,
                'date_deadline': due_date,
            }
            
            activity = Activity.create(activity_vals)
            _logger.info(f"Created review activity {activity.id} for invoice {invoice.name}")
            
        except Exception as e:
            _logger.warning(f"Failed to create review activity: {e}")

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
