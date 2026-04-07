"""PDF Invoice Processing with Multi-Tier Matching"""

import logging
import base64
import json
import io
import re
import uuid
from typing import Dict, Optional, List, Tuple, Any
from datetime import date, timedelta

from odoo import exceptions, fields

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


class PartnerNotFoundError(Exception):
    """Raised when a partner cannot be matched with required criteria"""
    pass


class PartnerMatcher:
    """Enhanced partner matching with VAT normalization and strict rules"""

    def __init__(self, env):
        self.env = env

    @staticmethod
    def normalize_vat(vat: str) -> str:
        """
        Normalize VAT number for comparison
        - Remove spaces, dashes, dots
        - Handle country prefix variations (AR-12345678 vs AR12345678)
        - Uppercase
        """
        if not vat:
            return ""
        # Remove common separators
        normalized = re.sub(r'[\s\-\.\,]', '', vat)
        # Uppercase
        normalized = normalized.upper()
        return normalized

    def find_partner(self, extracted_name: str, extracted_vat: str = None,
                     create_if_missing: bool = True, invoice_data: Dict = None) -> Tuple[Any, str, bool]:
        """
        Find partner with matching, create if not found

        Args:
            extracted_name: Vendor name from invoice
            extracted_vat: VAT number from invoice
            create_if_missing: If True, create vendor when not found
            invoice_data: Full invoice data for additional vendor info

        Returns:
            Tuple of (partner_record, match_type, was_created)
            - match_type: 'vat_match', 'name_exact', 'name_fuzzy', 'created'
            - was_created: True if vendor was auto-created (needs review)
        """
        Partner = self.env['res.partner']
        invoice_data = invoice_data or {}

        # 1. VAT exact match (most reliable)
        if extracted_vat:
            normalized_vat = self.normalize_vat(extracted_vat)
            _logger.info(f"[PartnerMatcher] Searching by VAT: {normalized_vat}")

            # Search with normalized VAT
            partners = Partner.search([('supplier_rank', '>', 0)])
            for partner in partners:
                if partner.vat and self.normalize_vat(partner.vat) == normalized_vat:
                    _logger.info(f"[PartnerMatcher] Found by VAT: {partner.name}")
                    return partner, 'vat_match', False

        # 2. Name exact match (case-insensitive)
        if extracted_name:
            _logger.info(f"[PartnerMatcher] Searching by name: {extracted_name}")

            # Exact name match
            partner = Partner.search([
                ('name', '=ilike', extracted_name.strip()),
                ('supplier_rank', '>', 0)
            ], limit=1)

            if partner:
                _logger.info(f"[PartnerMatcher] Found by exact name: {partner.name}")
                return partner, 'name_exact', False

            # Try partial/fuzzy name match
            partner = Partner.search([
                ('name', 'ilike', extracted_name.strip()),
                ('supplier_rank', '>', 0)
            ], limit=1)

            if partner:
                _logger.info(f"[PartnerMatcher] Found by fuzzy name: {partner.name}")
                return partner, 'name_fuzzy', False

        # 3. No match found - create new vendor if allowed
        if create_if_missing:
            return self._create_vendor(extracted_name, extracted_vat, invoice_data)

        # 4. No match and creation not allowed
        raise PartnerNotFoundError(
            f"No partner found matching name '{extracted_name}' or VAT '{extracted_vat}'. "
            "Please create the partner first."
        )

    def _create_vendor(self, name: str, vat: str = None, invoice_data: Dict = None) -> Tuple[Any, str, bool]:
        """
        Create a new vendor from invoice data

        Returns:
            Tuple of (partner_record, 'created', True)
        """
        Partner = self.env['res.partner']
        invoice_data = invoice_data or {}

        vendor_vals = {
            'name': name or 'Unknown Vendor',
            'supplier_rank': 1,
            'customer_rank': 0,
            'is_company': True,
            'company_type': 'company',
        }

        if vat:
            vendor_vals['vat'] = vat

        # Add additional info from invoice if available
        if invoice_data.get('vendor_address'):
            vendor_vals['street'] = invoice_data['vendor_address']

        if invoice_data.get('vendor_phone'):
            vendor_vals['phone'] = invoice_data['vendor_phone']

        if invoice_data.get('vendor_email'):
            vendor_vals['email'] = invoice_data['vendor_email']

        # Add note that this was auto-created
        vendor_vals['comment'] = (
            "⚠️ AUTO-CREATED FROM PDF INVOICE\n"
            "This vendor was automatically created during PDF invoice processing.\n"
            "Please review and complete the vendor information."
        )

        try:
            vendor = Partner.create(vendor_vals)
            _logger.info(f"[PartnerMatcher] Created new vendor: {vendor.name} (ID: {vendor.id}, VAT: {vat})")
            return vendor, 'created', True
        except Exception as e:
            _logger.error(f"[PartnerMatcher] Failed to create vendor: {e}")
            raise PartnerNotFoundError(f"Failed to create vendor '{name}': {str(e)}")


class ProductMatcher:
    """Multi-tier product matching with confidence tracking"""

    def __init__(self, env):
        self.env = env

    def match_product(self, line_description: str, vendor_id: int = None,
                      line_data: Dict = None) -> Dict:
        """
        Multi-tier product matching with confidence tracking

        Returns dict with:
            - product: product.product record or None
            - match_type: exact|supplier_mapping|fuzzy_auto|fuzzy_review|ai_semantic|placeholder
            - confidence: 0.0-1.0
            - needs_review: bool
            - message: str or None
        """
        result = {
            'product': None,
            'match_type': None,
            'confidence': 0,
            'needs_review': False,
            'message': None
        }

        line_data = line_data or {}
        Product = self.env['product.product']

        # Tier 1: Exact match (SKU, barcode, exact name)
        product = self._exact_match(line_description)
        if product:
            result.update(product=product, match_type='exact', confidence=1.0)
            _logger.info(f"[ProductMatcher] Tier 1 exact match: {product.name}")
            return result

        # Tier 2: Supplier product mapping (product.supplierinfo)
        if vendor_id:
            product = self._match_by_supplier_info(vendor_id, line_description)
            if product:
                result.update(product=product, match_type='supplier_mapping', confidence=0.95)
                _logger.info(f"[ProductMatcher] Tier 2 supplier mapping: {product.name}")
                return result

        # Tier 3: Fuzzy matching
        product, score = self._fuzzy_match(line_description, vendor_id)
        if product and score > 0.85:
            result.update(product=product, match_type='fuzzy_auto', confidence=score)
            _logger.info(f"[ProductMatcher] Tier 3 fuzzy auto ({score:.0%}): {product.name}")
            return result
        elif product and score > 0.6:
            result.update(
                product=product,
                match_type='fuzzy_review',
                confidence=score,
                needs_review=True,
                message=f"Fuzzy match ({score:.0%}): '{line_description}' → '{product.name}'"
            )
            _logger.info(f"[ProductMatcher] Tier 3 fuzzy review ({score:.0%}): {product.name}")
            return result

        # Tier 4: AI semantic matching (if enabled)
        ai_result = self._ai_semantic_match(line_description, vendor_id)
        if ai_result and ai_result.get('product'):
            confidence = ai_result.get('confidence', 0)
            result.update(
                product=ai_result['product'],
                match_type='ai_semantic',
                confidence=confidence,
                needs_review=confidence < 0.85,
                message=ai_result.get('reasoning')
            )
            _logger.info(f"[ProductMatcher] Tier 4 AI match ({confidence:.0%}): {ai_result['product'].name}")
            return result

        # Tier 5: Create placeholder product
        product = self._create_placeholder_product(line_description, vendor_id, line_data)
        result.update(
            product=product,
            match_type='placeholder',
            confidence=0,
            needs_review=True,
            message=f"No match found. Created placeholder product for '{line_description}'"
        )
        _logger.info(f"[ProductMatcher] Tier 5 placeholder created: {product.name}")
        return result

    def _exact_match(self, line_description: str):
        """Tier 1: Exact matches on SKU, barcode, name"""
        Product = self.env['product.product']

        # Extract potential SKU/barcode from description
        sku_match = re.search(r'\b([A-Z]{2,}[-]?\d{3,}|\d{8,13})\b', line_description.upper())

        if sku_match:
            code = sku_match.group(1)
            # Try default_code (SKU)
            product = Product.search([('default_code', '=', code)], limit=1)
            if product:
                return product
            # Try barcode
            product = Product.search([('barcode', '=', code)], limit=1)
            if product:
                return product

        # Exact name match
        product = Product.search([('name', '=ilike', line_description.strip())], limit=1)
        if product:
            return product

        return None

    def _match_by_supplier_info(self, vendor_id: int, product_name: str):
        """Tier 2: Match using product.supplierinfo (vendor product mapping)"""
        SupplierInfo = self.env['product.supplierinfo']

        # Search by vendor's product name
        supplierinfo = SupplierInfo.search([
            ('partner_id', '=', vendor_id),
            ('product_name', '=ilike', product_name.strip())
        ], limit=1)

        if supplierinfo and supplierinfo.product_tmpl_id:
            # Get the product variant
            product = supplierinfo.product_tmpl_id.product_variant_id
            if product:
                return product

        # Try partial match on supplier's product name
        supplierinfo = SupplierInfo.search([
            ('partner_id', '=', vendor_id),
            ('product_name', 'ilike', product_name.strip()[:30])
        ], limit=1)

        if supplierinfo and supplierinfo.product_tmpl_id:
            return supplierinfo.product_tmpl_id.product_variant_id

        return None

    def _fuzzy_match(self, line_description: str, vendor_id: int = None) -> Tuple[Any, float]:
        """Tier 3: Fuzzy/similarity matching"""
        Product = self.env['product.product']

        # Get candidate products
        domain = [('purchase_ok', '=', True)]
        candidates = Product.search(domain, limit=100)

        if not candidates:
            return None, 0

        best_match = None
        best_score = 0

        desc_lower = line_description.lower().strip()
        desc_words = set(desc_lower.split())

        for product in candidates:
            # Calculate similarity score
            product_name_lower = (product.name or '').lower()
            product_words = set(product_name_lower.split())

            # Word overlap score
            if desc_words and product_words:
                overlap = len(desc_words & product_words)
                total = len(desc_words | product_words)
                word_score = overlap / total if total > 0 else 0
            else:
                word_score = 0

            # Substring containment bonus
            containment_score = 0
            if desc_lower in product_name_lower or product_name_lower in desc_lower:
                containment_score = 0.3

            # Check supplier aliases
            alias_score = 0
            for seller in product.seller_ids:
                if seller.product_name:
                    seller_name_lower = seller.product_name.lower()
                    if desc_lower in seller_name_lower or seller_name_lower in desc_lower:
                        alias_score = 0.4
                        break

            score = min(1.0, word_score + containment_score + alias_score)

            if score > best_score:
                best_score = score
                best_match = product

        return best_match, best_score

    def _ai_semantic_match(self, line_description: str, vendor_id: int = None) -> Optional[Dict]:
        """Tier 4: AI-assisted semantic matching"""
        try:
            Product = self.env['product.product']

            # Get candidates
            candidates = Product.search([('purchase_ok', '=', True)], limit=20)
            if not candidates:
                return None

            # Format candidates for AI
            candidate_list = "\n".join([
                f"ID:{p.id} | {p.name} | Code:{p.default_code or 'N/A'}"
                for p in candidates
            ])

            # Get AI config
            config = self.env['res.config.settings'].get_ai_config()
            if not config.get('api_key'):
                return None

            from .ai_provider import OpenRouterProvider
            ai_provider = OpenRouterProvider(
                api_key=config['api_key'],
                model=config['model'],
                site_url=config['site_url'],
                site_name=config['site_name']
            )

            prompt = f"""Match this supplier product description to the most likely internal product.

Supplier description: "{line_description}"

Internal products:
{candidate_list}

Consider:
- Same product, different brand names
- Abbreviated vs full names
- Size/unit variations
- Industry-specific terminology

Return ONLY a JSON object (no markdown):
{{"product_id": <ID or null>, "confidence": <0.0-1.0>, "reasoning": "<brief explanation>"}}

If no confident match (confidence < 0.5), return {{"product_id": null, "confidence": 0, "reasoning": "..."}}"""

            messages = [
                {'role': 'system', 'content': 'You are an expert at matching product descriptions. Return only valid JSON.'},
                {'role': 'user', 'content': prompt}
            ]

            response = ai_provider.chat(messages=messages, temperature=0.1, max_tokens=200)
            ai_text = response.get('choices', [{}])[0].get('message', {}).get('content', '')

            # Parse JSON response
            try:
                # Extract JSON from response
                json_match = re.search(r'\{[^}]+\}', ai_text)
                if json_match:
                    ai_result = json.loads(json_match.group())

                    if ai_result.get('product_id') and ai_result.get('confidence', 0) >= 0.5:
                        product = Product.browse(ai_result['product_id'])
                        if product.exists():
                            return {
                                'product': product,
                                'confidence': ai_result['confidence'],
                                'reasoning': ai_result.get('reasoning', '')
                            }
            except (json.JSONDecodeError, ValueError) as e:
                _logger.warning(f"[ProductMatcher] AI response parse error: {e}")

            return None

        except Exception as e:
            _logger.warning(f"[ProductMatcher] AI semantic match failed: {e}")
            return None

    def _create_placeholder_product(self, line_description: str, vendor_id: int = None,
                                     line_data: Dict = None) -> Any:
        """Tier 5: Create placeholder product for manual review"""
        Product = self.env['product.product']
        SupplierInfo = self.env['product.supplierinfo']

        line_data = line_data or {}

        # Generate unique code
        unique_id = uuid.uuid4().hex[:8].upper()
        default_code = f"PENDING-{unique_id}"

        product_vals = {
            'name': f"[TO MATCH] {line_description[:100]}",
            'type': 'consu',  # Consumable as safe default
            'purchase_ok': True,
            'sale_ok': False,  # Don't sell until reviewed
            'default_code': default_code,
            'description_purchase': f"Original description: {line_description}\n\nNeeds manual product matching.",
        }

        product = Product.create(product_vals)

        # Create supplier pricelist entry for future matching
        if vendor_id:
            SupplierInfo.create({
                'partner_id': vendor_id,
                'product_tmpl_id': product.product_tmpl_id.id,
                'product_name': line_description[:128],
                'price': line_data.get('unit_price', 0),
            })

        return product


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
            extraction_method = 'pypdf2'

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
                            extraction_method = 'tesseract'
                            _logger.info("Using traditional OCR text")
                        else:
                            _logger.info("Traditional OCR didn't extract enough text, trying AI OCR...")
                            # Try AI-based OCR as fallback (costs money but more accurate)
                            ai_ocr_text = self._extract_text_ai_ocr(pdf_content)
                            if ai_ocr_text and len(ai_ocr_text.strip()) > ocr_length:
                                text = ai_ocr_text
                                text_length = len(ai_ocr_text.strip())
                                extraction_method = 'vision_ai'
                                _logger.info("Using AI OCR text (premium)")
                else:
                    _logger.info("Traditional OCR not available, trying AI OCR...")
                    # No traditional OCR available, try AI directly
                    ai_ocr_text = self._extract_text_ai_ocr(pdf_content)
                    if ai_ocr_text:
                        text = ai_ocr_text
                        text_length = len(ai_ocr_text.strip())
                        extraction_method = 'vision_ai'
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
                'filename': filename,
                'ocr_method': extraction_method,
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
            
            # Convert PDF to images (high DPI improves OCR on small fonts)
            dpi = int(self.env['ir.config_parameter'].sudo().get_param('odoo_ai_chat.ocr_dpi', '300'))
            images = convert_from_bytes(pdf_content, dpi=dpi)
            _logger.info(f"Converted PDF to {len(images)} images")
            
            text_parts = []
            
            for page_num, image in enumerate(images, 1):
                _logger.info(f"OCR processing page {page_num}...")
                
                # Preprocess to improve OCR quality (contrast/binarize/scale).
                processed = self._preprocess_image_for_ocr(image)

                # Configure Tesseract for invoice-like documents.
                # Avoid whitelists: invoices often contain symbols/accents that whitelists destroy.
                psm = self.env['ir.config_parameter'].sudo().get_param('odoo_ai_chat.ocr_psm', '6')
                custom_config = f'--oem 3 --psm {psm}'

                # Language selection: default to eng+spa; can be overridden in config.
                lang = self.env['ir.config_parameter'].sudo().get_param('odoo_ai_chat.ocr_lang', 'eng+spa')
                
                # Extract text using Tesseract
                try:
                    page_text = pytesseract.image_to_string(processed, lang=lang, config=custom_config)
                    
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

    def _preprocess_image_for_ocr(self, image):
        """Preprocess PIL image for better OCR (grayscale, contrast, binarize, enlarge)."""
        try:
            from PIL import ImageEnhance, ImageOps

            img = image.convert('RGB')
            img = ImageOps.grayscale(img)
            img = ImageOps.autocontrast(img)
            img = ImageEnhance.Contrast(img).enhance(1.6)

            w, h = img.size
            if max(w, h) < 2000:
                img = img.resize((w * 2, h * 2), resample=3)  # 3 = BICUBIC

            threshold = int(self.env['ir.config_parameter'].sudo().get_param('odoo_ai_chat.ocr_threshold', '170'))
            img = img.point(lambda p: 255 if p > threshold else 0, mode='1')
            return img
        except Exception as e:
            _logger.debug(f"OCR preprocessing failed, using original image: {e}")
            return image

    def _extract_text_ai_ocr(self, pdf_content: bytes) -> str:
        """Extract text using AI vision models (premium but highly accurate)"""
        try:
            _logger.info("Attempting AI-based OCR using vision model...")
            
            # Convert PDF to high-quality images
            if not OCR_AVAILABLE:
                _logger.warning("pdf2image not available for AI OCR")
                return ""
            
            images = convert_from_bytes(pdf_content, dpi=200)  # Lower DPI for AI (faster)
            
            if not images:
                return ""
            
            # Use only first 3 pages to control costs
            pages_to_process = min(3, len(images))
            _logger.info(f"Processing first {pages_to_process} pages with AI OCR")
            
            text_parts = []
            
            for page_num in range(pages_to_process):
                try:
                    image = self._preprocess_image_for_ocr(images[page_num])
                    
                    # Convert PIL Image to base64 for AI
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
                        model=self.env['ir.config_parameter'].sudo().get_param(
                            'odoo_ai_chat.vision_ocr_model',
                            'openai/gpt-4o-mini'
                        ),
                        site_url=config['site_url'],
                        site_name=config['site_name']
                    )
                    
                    # Vision prompt for OCR (OpenAI-compatible; OpenRouter normalizes per-model).
                    messages = [
                        {
                            'role': 'user',
                            'content': [
                                {
                                    'type': 'text',
                                    'text': (
                                        "Extract all text from this invoice image as accurately as possible.\n"
                                        "Return ONLY the raw text (no markdown, no JSON, no explanations).\n"
                                        "Preserve line breaks. Pay special attention to invoice numbers, dates, VAT/Tax IDs, totals, and line items."
                                    )
                                },
                                {
                                    'type': 'image_url',
                                    'image_url': {'url': f'data:image/png;base64,{image_b64}'}
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

    def _check_duplicate_invoice(self, invoice_number: str, vendor_vat: str = None, vendor_name: str = None):
        """
        Check if an invoice with the same reference already exists.

        Args:
            invoice_number: Invoice reference number from PDF
            vendor_vat: Vendor VAT for additional matching
            vendor_name: Vendor name for additional matching

        Returns:
            Existing account.move record if found, None otherwise
        """
        Invoice = self.env['account.move']

        # Search for existing vendor bills with same reference
        domain = [
            ('move_type', '=', 'in_invoice'),
            ('ref', '=', invoice_number),
        ]

        existing = Invoice.search(domain, limit=1)

        if existing:
            _logger.info(f"[PDFProcessor] Found existing invoice with ref '{invoice_number}': {existing.name}")
            return existing

        # Also check if reference is in the name field
        domain_name = [
            ('move_type', '=', 'in_invoice'),
            ('name', 'ilike', invoice_number),
        ]

        existing = Invoice.search(domain_name, limit=1)

        if existing:
            _logger.info(f"[PDFProcessor] Found existing invoice with name containing '{invoice_number}': {existing.name}")
            return existing

        return None

    def create_vendor_bill(self, invoice_data: Dict, pdf_content_b64: str = None,
                          filename: str = None) -> Dict:
        """
        Create vendor bill from parsed PDF data with partial success handling.

        Core principle: Always create as much as possible, never fail completely.
        Document State: Always create in draft state (never confirm automatically).

        Args:
            invoice_data: Parsed invoice data dict
            pdf_content_b64: Base64 encoded PDF content
            filename: Original filename

        Returns:
            Dict with invoice creation result including partial success info
        """
        result = {
            'success': False,
            'partial_success': False,
            'invoice_id': None,
            'invoice_name': None,
            'vendor_name': None,
            'vendor_matched': False,
            'vendor_match_type': None,
            'vendor_created': False,  # True if vendor was auto-created
            'total': 0,
            'currency': None,
            'lines_processed': 0,
            'lines_needing_review': 0,
            'products_needing_review': [],
            'match_summary': {},
            'warnings': [],
            'errors': [],
            'message': '',
        }

        try:
            # Step 0: Check for duplicate invoice
            invoice_number = invoice_data.get('invoice_number', '').strip()
            vendor_vat = invoice_data.get('vendor_vat', '').strip() if invoice_data.get('vendor_vat') else None
            vendor_name = invoice_data.get('vendor_name', '').strip()

            if invoice_number:
                # Check if invoice with same reference already exists
                existing = self._check_duplicate_invoice(invoice_number, vendor_vat, vendor_name)
                if existing:
                    result['success'] = False
                    result['errors'].append(f"Duplicate invoice: {invoice_number} already exists as {existing.name}")
                    result['message'] = (
                        f"⚠️ **Invoice already exists**\n\n"
                        f"An invoice with reference '{invoice_number}' already exists:\n"
                        f"- **Existing Invoice:** {existing.name}\n"
                        f"- **Vendor:** {existing.partner_id.name}\n"
                        f"- **Amount:** {existing.currency_id.symbol}{existing.amount_total:,.2f}\n\n"
                        f"No duplicate was created."
                    )
                    _logger.info(f"[PDFProcessor] Duplicate invoice detected: {invoice_number} -> {existing.name}")
                    return result

            # Step 1: Find or create vendor
            vendor = None
            vendor_was_created = False
            try:
                vendor, vendor_match_type, vendor_was_created = self._find_or_create_vendor(
                    invoice_data, create_if_missing=True
                )
                result['vendor_matched'] = True
                result['vendor_name'] = vendor.name
                result['vendor_match_type'] = vendor_match_type

                if vendor_was_created:
                    result['vendor_created'] = True
                    result['warnings'].append(f"New vendor '{vendor.name}' was auto-created and needs review")
                    _logger.info(f"[PDFProcessor] Auto-created vendor: {vendor.name}")

            except PartnerNotFoundError as e:
                # Partner not found and creation failed
                result['errors'].append(str(e))
                result['message'] = f"❌ Cannot create invoice: {str(e)}"
                _logger.warning(f"[PDFProcessor] Partner not found, cannot proceed: {e}")
                return result

            # Step 2: Create invoice lines with multi-tier product matching
            lines_result = self._create_invoice_lines(invoice_data, vendor_id=vendor.id)
            invoice_lines = lines_result['lines']
            products_needing_review = lines_result['products_needing_review']
            match_summary = lines_result['match_summary']

            result['match_summary'] = match_summary
            result['lines_processed'] = match_summary['total_lines']
            result['lines_needing_review'] = len(products_needing_review)
            result['products_needing_review'] = products_needing_review

            if not invoice_lines:
                result['errors'].append("No valid line items could be extracted from the invoice")
                result['message'] = "❌ Cannot create invoice: No valid line items found"
                return result

            # Step 3: Create invoice (always in draft state)
            Invoice = self.env['account.move']

            invoice_vals = {
                'partner_id': vendor.id,
                'move_type': 'in_invoice',
                'invoice_date': invoice_data.get('invoice_date'),
                'invoice_date_due': invoice_data.get('due_date'),
                'ref': invoice_data.get('invoice_number'),
                'invoice_line_ids': invoice_lines,
                'narration': invoice_data.get('notes'),
                # Note: state='draft' is the default, no need to explicitly set
            }

            # Set currency if provided
            if invoice_data.get('currency'):
                Currency = self.env['res.currency']
                currency = Currency.search([('name', '=', invoice_data['currency'])], limit=1)
                if currency:
                    invoice_vals['currency_id'] = currency.id

            invoice = Invoice.create(invoice_vals)

            result['invoice_id'] = invoice.id
            result['invoice_name'] = invoice.name
            result['total'] = invoice.amount_total
            result['currency'] = invoice.currency_id.name

            # Step 4: Attach PDF if provided
            if pdf_content_b64 and filename:
                self._attach_pdf_to_invoice(invoice, pdf_content_b64, filename)

            # Step 5: Post processing summary to chatter
            self._post_processing_summary(invoice, match_summary, products_needing_review)

            # Step 6: Create activity reminder for review if needed
            needs_review = (
                len(products_needing_review) > 0 or
                match_summary.get('placeholders_created', 0) > 0 or
                match_summary.get('fuzzy_review_matches', 0) > 0
            )

            if needs_review:
                self._create_enhanced_review_activity(invoice, vendor, products_needing_review, match_summary)
                result['warnings'].append(f"{len(products_needing_review)} products require manual review")

            # Step 7: Determine success status
            if products_needing_review:
                result['partial_success'] = True
                result['success'] = True
            else:
                result['success'] = True

            # Build success message
            result['message'] = self._build_success_message(result, match_summary)

            _logger.info(f"[PDFProcessor] Created vendor bill {invoice.name} for {vendor.name}")

            return result

        except Exception as e:
            _logger.exception("[PDFProcessor] Error creating vendor bill from PDF")
            result['errors'].append(str(e))
            result['message'] = f"❌ Error creating invoice: {str(e)}"
            return result

    def _build_success_message(self, result: Dict, match_summary: Dict) -> str:
        """Build a user-friendly success message"""
        lines = []

        if result['partial_success']:
            lines.append(f"⚠️ **Invoice created with items needing review**")
        else:
            lines.append(f"✅ **Invoice created successfully**")

        lines.append(f"")
        lines.append(f"📄 **Invoice:** {result['invoice_name']}")

        # Show vendor info with creation status
        if result.get('vendor_created'):
            lines.append(f"🏢 **Vendor:** {result['vendor_name']} ⚠️ (NEW - auto-created, needs review)")
        else:
            lines.append(f"🏢 **Vendor:** {result['vendor_name']} ✅ (matched)")

        lines.append(f"💰 **Total:** {result['currency']} {result['total']:,.2f}")

        # Matching summary
        lines.append(f"")
        lines.append(f"📊 **Product Matching Summary:**")
        lines.append(f"  • Total lines: {match_summary.get('total_lines', 0)}")
        if match_summary.get('exact_matches', 0) > 0:
            lines.append(f"  • ✅ Exact matches: {match_summary['exact_matches']}")
        if match_summary.get('supplier_matches', 0) > 0:
            lines.append(f"  • ✅ Supplier mappings: {match_summary['supplier_matches']}")
        if match_summary.get('fuzzy_auto_matches', 0) > 0:
            lines.append(f"  • ✅ Auto fuzzy matches: {match_summary['fuzzy_auto_matches']}")
        if match_summary.get('ai_matches', 0) > 0:
            lines.append(f"  • ✅ AI matches: {match_summary['ai_matches']}")
        if match_summary.get('fuzzy_review_matches', 0) > 0:
            lines.append(f"  • ⚠️ Fuzzy (needs review): {match_summary['fuzzy_review_matches']}")
        if match_summary.get('placeholders_created', 0) > 0:
            lines.append(f"  • ⚠️ Placeholders created: {match_summary['placeholders_created']}")

        if result['products_needing_review']:
            lines.append(f"")
            lines.append(f"⚠️ **Products needing review ({len(result['products_needing_review'])}):**")
            for idx, prod in enumerate(result['products_needing_review'][:5], 1):
                lines.append(f"  {idx}. {prod['original_description'][:50]}...")
            if len(result['products_needing_review']) > 5:
                lines.append(f"  ... and {len(result['products_needing_review']) - 5} more")

        lines.append(f"")
        lines.append(f"📝 A review activity has been scheduled for this invoice.")

        return "\n".join(lines)

    def _post_processing_summary(self, invoice, match_summary: Dict, products_needing_review: List):
        """Post a processing summary to the invoice chatter"""
        try:
            # Build HTML message for chatter
            html_parts = [
                "<h3>🤖 AI Invoice Processing Summary</h3>",
                "<p><strong>Product Matching Results:</strong></p>",
                "<ul>",
                f"<li>Total line items: {match_summary.get('total_lines', 0)}</li>",
            ]

            if match_summary.get('exact_matches', 0) > 0:
                html_parts.append(f"<li>✅ Exact matches: {match_summary['exact_matches']}</li>")
            if match_summary.get('supplier_matches', 0) > 0:
                html_parts.append(f"<li>✅ Supplier mapping matches: {match_summary['supplier_matches']}</li>")
            if match_summary.get('fuzzy_auto_matches', 0) > 0:
                html_parts.append(f"<li>✅ High-confidence fuzzy matches: {match_summary['fuzzy_auto_matches']}</li>")
            if match_summary.get('ai_matches', 0) > 0:
                html_parts.append(f"<li>✅ AI semantic matches: {match_summary['ai_matches']}</li>")
            if match_summary.get('fuzzy_review_matches', 0) > 0:
                html_parts.append(f"<li>⚠️ Low-confidence fuzzy matches (review needed): {match_summary['fuzzy_review_matches']}</li>")
            if match_summary.get('placeholders_created', 0) > 0:
                html_parts.append(f"<li>⚠️ Placeholder products created (review needed): {match_summary['placeholders_created']}</li>")

            html_parts.append("</ul>")

            if products_needing_review:
                html_parts.extend([
                    "<p><strong>⚠️ Products Requiring Review:</strong></p>",
                    "<table style='border-collapse: collapse; width: 100%;'>",
                    "<tr style='background: #f5f5f5;'>",
                    "<th style='border: 1px solid #ddd; padding: 8px;'>Original Description</th>",
                    "<th style='border: 1px solid #ddd; padding: 8px;'>Matched Product</th>",
                    "<th style='border: 1px solid #ddd; padding: 8px;'>Match Type</th>",
                    "<th style='border: 1px solid #ddd; padding: 8px;'>Confidence</th>",
                    "</tr>",
                ])

                for prod in products_needing_review[:10]:
                    confidence_pct = f"{prod['confidence'] * 100:.0f}%" if prod['confidence'] else "N/A"
                    html_parts.append(
                        f"<tr>"
                        f"<td style='border: 1px solid #ddd; padding: 8px;'>{prod['original_description'][:50]}</td>"
                        f"<td style='border: 1px solid #ddd; padding: 8px;'>{prod['product_name'][:50]}</td>"
                        f"<td style='border: 1px solid #ddd; padding: 8px;'>{prod['match_type']}</td>"
                        f"<td style='border: 1px solid #ddd; padding: 8px;'>{confidence_pct}</td>"
                        f"</tr>"
                    )

                if len(products_needing_review) > 10:
                    html_parts.append(
                        f"<tr><td colspan='4' style='border: 1px solid #ddd; padding: 8px; text-align: center;'>"
                        f"... and {len(products_needing_review) - 10} more items</td></tr>"
                    )

                html_parts.append("</table>")

            html_parts.append("<p><em>This invoice was automatically created from PDF. Please review before confirming.</em></p>")

            # Post to chatter
            invoice.message_post(
                body="".join(html_parts),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

        except Exception as e:
            _logger.warning(f"[PDFProcessor] Failed to post processing summary: {e}")

    def _create_enhanced_review_activity(self, invoice, vendor, products_needing_review: List, match_summary: Dict):
        """Create an enhanced activity reminder with detailed review checklist"""
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
                todo_type = ActivityType.search([
                    '|', '|',
                    ('name', 'ilike', 'review'),
                    ('name', 'ilike', 'follow'),
                    ('name', 'ilike', 'call')
                ], limit=1)

            if not todo_type:
                _logger.warning("[PDFProcessor] No suitable activity type found")
                return

            due_date = date.today() + timedelta(days=1)

            # Build detailed note
            note_parts = [
                f"<h4>🤖 Auto-Generated Invoice Review Required</h4>",
                f"<p><strong>Invoice:</strong> {invoice.name}</p>",
                f"<p><strong>Vendor:</strong> {vendor.name}</p>",
                f"<p><strong>Amount:</strong> {invoice.currency_id.symbol}{invoice.amount_total:,.2f}</p>",
            ]

            if products_needing_review:
                note_parts.append(f"<h5>⚠️ Products Needing Review ({len(products_needing_review)}):</h5>")
                note_parts.append("<ul>")
                for prod in products_needing_review[:5]:
                    note_parts.append(
                        f"<li><strong>{prod['original_description'][:40]}</strong> → "
                        f"matched to '{prod['product_name'][:30]}' ({prod['match_type']})</li>"
                    )
                if len(products_needing_review) > 5:
                    note_parts.append(f"<li>...and {len(products_needing_review) - 5} more</li>")
                note_parts.append("</ul>")

            note_parts.extend([
                "<h5>✅ Review Checklist:</h5>",
                "<ul>",
                "<li>☐ Verify vendor is correct</li>",
                "<li>☐ Check product mappings are accurate</li>",
                "<li>☐ Confirm quantities and prices</li>",
                "<li>☐ Verify GL account assignments</li>",
                "<li>☐ Check tax calculations</li>",
            ])

            if match_summary.get('placeholders_created', 0) > 0:
                note_parts.append(
                    f"<li>☐ Map {match_summary['placeholders_created']} placeholder products to real products</li>"
                )

            note_parts.extend([
                "</ul>",
                "<p><em>After review, confirm the invoice or delete and re-process if needed.</em></p>",
            ])

            # Get the ir.model record for account.move (required for res_model_id)
            IrModel = self.env['ir.model']
            account_move_model = IrModel.sudo().search([('model', '=', 'account.move')], limit=1)

            if not account_move_model:
                _logger.warning("[PDFProcessor] Could not find ir.model for account.move")
                return

            activity_vals = {
                'activity_type_id': todo_type.id,
                'summary': f'Review AI Invoice: {invoice.name} ({len(products_needing_review)} items to check)',
                'note': "".join(note_parts),
                'res_id': invoice.id,
                'res_model_id': account_move_model.id,  # Use res_model_id instead of res_model
                'user_id': self.env.user.id,
                'date_deadline': due_date,
            }

            Activity.create(activity_vals)
            _logger.info(f"[PDFProcessor] Created enhanced review activity for invoice {invoice.name}")

        except Exception as e:
            _logger.warning(f"[PDFProcessor] Failed to create review activity: {e}")

    def _find_or_create_vendor(self, invoice_data: Dict, create_if_missing: bool = True) -> Tuple[Any, str, bool]:
        """
        Find existing vendor or create new one.

        Args:
            invoice_data: Parsed invoice data
            create_if_missing: If True, create vendor when not found

        Returns:
            Tuple of (partner_record, match_type, was_created)
            - was_created: True if vendor was auto-created (needs review)
        """
        vendor_name = invoice_data.get('vendor_name', '').strip()
        vendor_vat = invoice_data.get('vendor_vat', '').strip() if invoice_data.get('vendor_vat') else None

        _logger.info(f"[PDFProcessor] Finding vendor: name='{vendor_name}', vat='{vendor_vat}'")

        matcher = PartnerMatcher(self.env)

        # Find or create vendor
        partner, match_type, was_created = matcher.find_partner(
            vendor_name,
            vendor_vat,
            create_if_missing=create_if_missing,
            invoice_data=invoice_data
        )

        _logger.info(f"[PDFProcessor] Vendor result: {partner.name} via {match_type}, created={was_created}")
        return partner, match_type, was_created

    def _create_invoice_lines(self, invoice_data: Dict, vendor_id: int = None) -> Dict:
        """
        Create invoice lines using multi-tier product matching.

        Args:
            invoice_data: Parsed invoice data
            vendor_id: Vendor partner ID for supplier mapping lookup

        Returns:
            Dict with:
                - lines: List of (0, 0, vals) tuples for invoice creation
                - products_needing_review: List of products that need manual review
                - match_summary: Summary of matching results
        """
        invoice_lines = []
        products_needing_review = []
        match_summary = {
            'total_lines': 0,
            'exact_matches': 0,
            'supplier_matches': 0,
            'fuzzy_auto_matches': 0,
            'fuzzy_review_matches': 0,
            'ai_matches': 0,
            'placeholders_created': 0,
        }

        product_matcher = ProductMatcher(self.env)

        for line_data in invoice_data.get('lines', []):
            description = line_data.get('description', '').strip()

            if not description:
                continue

            match_summary['total_lines'] += 1
            _logger.info(f"[PDFProcessor] Processing line item: {description}")

            # Use multi-tier product matching
            match_result = product_matcher.match_product(
                line_description=description,
                vendor_id=vendor_id,
                line_data=line_data
            )

            product = match_result['product']
            match_type = match_result['match_type']

            # Track match types for summary
            if match_type == 'exact':
                match_summary['exact_matches'] += 1
            elif match_type == 'supplier_mapping':
                match_summary['supplier_matches'] += 1
            elif match_type == 'fuzzy_auto':
                match_summary['fuzzy_auto_matches'] += 1
            elif match_type == 'fuzzy_review':
                match_summary['fuzzy_review_matches'] += 1
            elif match_type == 'ai_semantic':
                match_summary['ai_matches'] += 1
            elif match_type == 'placeholder':
                match_summary['placeholders_created'] += 1

            # Track products needing review
            if match_result['needs_review']:
                products_needing_review.append({
                    'product_id': product.id if product else None,
                    'product_name': product.name if product else description,
                    'original_description': description,
                    'match_type': match_type,
                    'confidence': match_result['confidence'],
                    'message': match_result['message'],
                })

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
                        _logger.info(f"[PDFProcessor] Updated product {product.name} cost price to {line_vals['price_unit']}")

            invoice_lines.append((0, 0, line_vals))

        return {
            'lines': invoice_lines,
            'products_needing_review': products_needing_review,
            'match_summary': match_summary,
        }

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
