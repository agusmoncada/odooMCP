"""MCP Server Integration for Odoo"""

import json
import logging
import threading
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Removed pandas dependency - using pure Python implementation
# This avoids memory issues and dependency conflicts in Odoo v16
PANDAS_AVAILABLE = False

# Module-level cache for MCP server instances (one per database)
_mcp_server_cache = {}
_cache_lock = threading.Lock()


class MCPServer:
    """
    Model Context Protocol (MCP) Server implementation.

    This class provides MCP server functionality to expose Odoo data
    and operations to AI assistants.
    """

    def __init__(self, env):
        self.env = env
        self._tools = {}
        self._resources = {}
        self._prompts = {}
        self._initialize_tools()

    def _check_user_permissions(self, model: str, operation: str, record_id: int = None) -> Dict:
        """
        Check if the current user has permission to perform an operation on a model.

        Args:
            model: The Odoo model name (e.g., 'res.partner')
            operation: One of 'read', 'create', 'write', 'unlink'
            record_id: Optional record ID for record-level access checks

        Returns:
            Dict with 'allowed' (bool), 'error' (str if not allowed), and 'details' (dict)
        """
        try:
            # Get the model
            try:
                Model = self.env[model]
            except KeyError:
                return {
                    'allowed': False,
                    'error': f"Model '{model}' not found. The required module may not be installed.",
                    'details': {'model': model, 'operation': operation}
                }

            user = self.env.user
            _logger.info(f"[Permission Check] User '{user.name}' (ID: {user.id}) checking '{operation}' on '{model}'")

            # Map operation to Odoo access right
            operation_map = {
                'read': 'read',
                'create': 'create',
                'write': 'write',
                'update': 'write',
                'unlink': 'unlink',
                'delete': 'unlink'
            }
            odoo_operation = operation_map.get(operation, operation)

            # Check model-level access rights using check_access_rights
            # This checks ir.model.access rules
            try:
                Model.check_access_rights(odoo_operation, raise_exception=True)
            except Exception as access_error:
                error_msg = str(access_error)
                _logger.warning(f"[Permission Check] Access denied for user '{user.name}' to {odoo_operation} on {model}: {error_msg}")

                # Provide user-friendly error message
                friendly_operation = {
                    'read': 'view',
                    'create': 'create',
                    'write': 'modify',
                    'unlink': 'delete'
                }.get(odoo_operation, odoo_operation)

                return {
                    'allowed': False,
                    'error': f"You don't have permission to {friendly_operation} records in {model}. Please contact your administrator if you need access.",
                    'details': {
                        'model': model,
                        'operation': odoo_operation,
                        'user': user.name,
                        'user_id': user.id,
                        'technical_error': error_msg
                    }
                }

            # If a specific record ID is provided, also check record-level rules
            if record_id:
                try:
                    record = Model.browse(record_id)
                    if not record.exists():
                        return {
                            'allowed': False,
                            'error': f"Record {model}({record_id}) not found.",
                            'details': {'model': model, 'record_id': record_id}
                        }

                    # Check record-level access using check_access_rule
                    # This checks ir.rule (record rules)
                    record.check_access_rule(odoo_operation)

                except Exception as rule_error:
                    error_msg = str(rule_error)
                    _logger.warning(f"[Permission Check] Record rule denied for user '{user.name}' on {model}({record_id}): {error_msg}")

                    friendly_operation = {
                        'read': 'view',
                        'create': 'create',
                        'write': 'modify',
                        'unlink': 'delete'
                    }.get(odoo_operation, odoo_operation)

                    return {
                        'allowed': False,
                        'error': f"You don't have permission to {friendly_operation} this specific record. This may be due to record-level security rules.",
                        'details': {
                            'model': model,
                            'record_id': record_id,
                            'operation': odoo_operation,
                            'user': user.name,
                            'technical_error': error_msg
                        }
                    }

            _logger.info(f"[Permission Check] Access granted for user '{user.name}' to {odoo_operation} on {model}")
            return {
                'allowed': True,
                'error': None,
                'details': {
                    'model': model,
                    'operation': odoo_operation,
                    'user': user.name,
                    'user_id': user.id,
                    'record_id': record_id
                }
            }

        except Exception as e:
            _logger.exception(f"[Permission Check] Unexpected error checking permissions")
            return {
                'allowed': False,
                'error': f"Error checking permissions: {str(e)}",
                'details': {'model': model, 'operation': operation}
            }

    def _sanitize_for_json(self, data):
        """Convert non-JSON-serializable types to JSON-safe formats"""
        from datetime import datetime, date, time
        from decimal import Decimal

        if isinstance(data, dict):
            return {key: self._sanitize_for_json(value) for key, value in data.items()}
        elif isinstance(data, (list, tuple)):
            return [self._sanitize_for_json(item) for item in data]
        elif isinstance(data, (datetime, date, time)):
            return data.isoformat()
        elif isinstance(data, Decimal):
            return float(data)
        elif isinstance(data, bytes):
            return data.decode('utf-8', errors='ignore')
        elif hasattr(data, '__iter__') and not isinstance(data, (str, bytes)):
            # Handle other iterables (like Odoo recordsets)
            return [self._sanitize_for_json(item) for item in data]
        else:
            return data

    def _initialize_tools(self):
        """Initialize available MCP tools"""
        self._tools = {
            'search_records': {
                'name': 'search_records',
                'description': 'Search and retrieve records from any Odoo model. Use this tool for: queries, counts, sums, checking status, listing data, getting totals, finding records. Returns actual data that you can analyze and present to user. This is your PRIMARY tool for data retrieval. IMPORTANT: For quotations, use model "sale.order" with domain [("state", "=", "draft")]. For confirmed sales orders, use [("state", "=", "sale")].',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string', 'description': 'The Odoo model name (e.g., res.partner)'},
                        'domain': {
                            'type': 'array',
                            'items': {},  # Allow any type of items in domain array
                            'description': 'Search domain (list of tuples)',
                            'default': []
                        },
                        'fields': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': 'Fields to return',
                            'default': []
                        },
                        'limit': {'type': 'integer', 'description': 'Maximum number of records', 'default': 10}
                    },
                    'required': ['model']
                }
            },
            'read_record': {
                'name': 'read_record',
                'description': 'Read a specific record from an Odoo model',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string', 'description': 'The Odoo model name'},
                        'record_id': {'type': 'integer', 'description': 'The record ID'},
                        'fields': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': 'Fields to return',
                            'default': []
                        }
                    },
                    'required': ['model', 'record_id']
                }
            },
            'create_record': {
                'name': 'create_record',
                'description': 'Create a new record in an Odoo model. PERMISSION CHECK: User permissions are verified before creation - only models the user has access to can be used. IMPORTANT: values parameter must be a JSON object (dict), not a string. Supported template variables in values: {{uid}} (current user ID), {{today}}, {{tomorrow}}, {{next_week_monday}}, {{next_monday}}, {{now}}, {{activity_type_id_for_call}}. For other dynamic values like partner_id or res_id, extract them from context or ask the user.',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string', 'description': 'The Odoo model name'},
                        'values': {'type': 'object', 'description': 'Field values for the new record as a JSON object (not a string). You can use template variables like {{uid}}, {{today}}, {{next_week_monday}}, etc.'}
                    },
                    'required': ['model', 'values']
                }
            },
            'write_record': {
                'name': 'write_record',
                'description': 'Update/modify/change existing records. PERMISSION CHECK: User permissions are verified before modification - only records the user has access to modify can be updated. Use when user asks to mark, update, change, or modify data. IMPORTANT: You MUST always provide the values parameter as a dict/object with the fields to update. Example: to mark sale order as sent, use values={"state": "sent"}. Common sale.order states: "draft", "sent", "sale", "done", "cancel".',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string', 'description': 'The Odoo model name (e.g., "sale.order", "res.partner")'},
                        'record_id': {'type': 'integer', 'description': 'The ID of the record to update'},
                        'values': {'type': 'object', 'description': 'Dictionary of field names and values to update. Example: {"state": "sent", "note": "Updated by AI"}. This parameter is REQUIRED.'}
                    },
                    'required': ['model', 'record_id', 'values']
                }
            },
            'get_model_fields': {
                'name': 'get_model_fields',
                'description': 'Get field information for an Odoo model',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string', 'description': 'The Odoo model name'}
                    },
                    'required': ['model']
                }
            },
            'generate_graph': {
                'name': 'generate_graph',
                'description': 'Generate a visual chart/graph ONLY when user explicitly asks for: "chart", "graph", "plot", "visualize", "show me a chart". DO NOT use for: sums, counts, queries, status checks, or when user just wants numbers. Use search_records instead for data queries. CRITICAL: Always use group_by parameter to create meaningful charts. EXAMPLES: "sales by customer" -> group_by="partner_id", "sales by product" -> group_by="product_id", "sales by status" -> group_by="state". Charts show values/totals on bars and percentages with amounts on pie charts.',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'graph_type': {
                            'type': 'string',
                            'enum': ['bar', 'column', 'line', 'pie', 'donut', 'horizontal_bar', 'stacked_bar', 'stacked', 'piled'],
                            'description': 'Type of graph: bar/column (vertical bars with values), horizontal_bar (horizontal bars), line (with filled area), pie (with % and amounts), donut (pie with center total), stacked_bar/stacked/piled (stacked columns for comparing multiple series)'
                        },
                        'model': {
                            'type': 'string',
                            'description': 'Odoo model to query (e.g., sale.order, account.move)'
                        },
                        'domain': {
                            'type': 'array',
                            'items': {},  # Allow any type of items in domain array
                            'description': 'Search domain for filtering records',
                            'default': []
                        },
                        'y_field': {
                            'type': 'string',
                            'description': 'Field for Y axis - numeric field to aggregate (e.g., amount_total, quantity)'
                        },
                        'group_by': {
                            'type': 'string',
                            'description': 'REQUIRED field to group data by for meaningful charts. Examples: "partner_id" for grouping by customer/client, "product_id" or "product_template_id" for grouping by product, "state" for grouping by status, "user_id" for grouping by salesperson. This creates separate bars/slices for each group. DO NOT use x_field for grouping - use group_by instead.'
                        },
                        'x_field': {
                            'type': 'string',
                            'description': 'Optional field for X axis (only for time series with date fields like create_date, date_order) - NOT for grouping by categories'
                        },
                        'aggregation': {
                            'type': 'string',
                            'enum': ['sum', 'avg', 'count', 'min', 'max'],
                            'description': 'Aggregation method for y_field',
                            'default': 'sum'
                        },
                        'title': {
                            'type': 'string',
                            'description': 'Graph title'
                        },
                        'date_range': {
                            'type': 'string',
                            'enum': ['week', 'month', 'quarter', 'year', 'all'],
                            'description': 'Time range for date-based graphs',
                            'default': 'month'
                        },
                        'limit': {
                            'type': 'integer',
                            'description': 'Maximum number of data points',
                            'default': 50
                        }
                    },
                    'required': ['graph_type', 'model', 'y_field', 'group_by']
                }
            },
            'create_vendor_bill_from_pdf': {
                'name': 'create_vendor_bill_from_pdf',
                'description': 'Create a vendor bill in Odoo from parsed PDF invoice data',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'invoice_data': {
                            'type': 'object',
                            'description': 'Parsed invoice data containing vendor, lines, amounts, etc.'
                        },
                        'pdf_content_b64': {
                            'type': 'string',
                            'description': 'Base64 encoded PDF content to attach to the invoice'
                        },
                        'filename': {
                            'type': 'string',
                            'description': 'Original PDF filename'
                        }
                    },
                    'required': ['invoice_data']
                }
            },
            'process_pdf_invoice': {
                'name': 'process_pdf_invoice',
                'description': 'Process uploaded PDF invoice using OCR and AI to automatically create vendor bill. Handles vendor/product creation and adds review activity. Use this when user uploads a PDF invoice.',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'attachment_id': {
                            'type': 'integer',
                            'description': 'ID of uploaded PDF attachment'
                        },
                        'filename': {
                            'type': 'string',
                            'description': 'Original filename of PDF'
                        }
                    },
                    'required': ['attachment_id']
                }
            },
            'create_activity': {
                'name': 'create_activity',
                'description': 'Create an activity/reminder for a record. Use this when user asks to be reminded to do something, create a task, or schedule a follow-up. Perfect for "remind me to call this client", "create a task to review this", etc. If the user is currently viewing a specific record (like a customer form), the activity will automatically be attached to that record - you only need to provide the summary.',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'res_model': {
                            'type': 'string',
                            'description': 'Model name of the record (e.g., res.partner, sale.order, account.move). Optional if user is currently viewing a record.'
                        },
                        'res_id': {
                            'type': 'integer',
                            'description': 'ID of the record to attach the activity to. Optional if user is currently viewing a record.'
                        },
                        'summary': {
                            'type': 'string',
                            'description': 'Brief summary of the activity (e.g., "Call client", "Review invoice")'
                        },
                        'note': {
                            'type': 'string',
                            'description': 'Detailed notes or description for the activity'
                        },
                        'activity_type': {
                            'type': 'string',
                            'enum': ['call', 'meeting', 'todo', 'email', 'follow_up'],
                            'description': 'Type of activity',
                            'default': 'todo'
                        },
                        'due_days': {
                            'type': 'integer',
                            'description': 'Number of days from today for the due date',
                            'default': 1
                        }
                    },
                    'required': ['summary']
                }
            },
            'read_group': {
                'name': 'read_group',
                'description': 'Aggregate and group records from an Odoo model. Use this for: summing values by category, counting records by field, getting totals grouped by product/partner/date, calculating averages per group. Perfect for "sum by product", "total by customer", "count by status", etc. IMPORTANT: For quotation totals, use model "sale.order" with domain [["state", "=", "draft"]] and fields ["amount_total:sum"].',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string', 'description': 'The Odoo model name (e.g., sale.order.line, account.move.line)'},
                        'domain': {
                            'type': 'array',
                            'items': {},
                            'description': 'Search domain to filter records (e.g., [["state", "=", "draft"]])',
                            'default': []
                        },
                        'fields': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': 'Fields to aggregate. Use "field:sum", "field:avg", "field:count", etc. Example: ["price_subtotal:sum", "product_uom_qty:sum"]',
                            'default': []
                        },
                        'groupby': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': 'Fields to group by (e.g., ["product_id"], ["partner_id", "state"])'
                        },
                        'orderby': {
                            'type': 'string',
                            'description': 'Order specification (e.g., "price_subtotal DESC")',
                            'default': ''
                        },
                        'limit': {
                            'type': 'integer',
                            'description': 'Maximum number of groups to return',
                            'default': 80
                        }
                    },
                    'required': ['model', 'groupby']
                }
            }
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return list of available MCP tools"""
        return list(self._tools.values())

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], view_context: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute an MCP tool with given arguments and optional view context"""
        try:
            if tool_name == 'search_records':
                return self._search_records(**arguments)
            elif tool_name == 'read_record':
                return self._read_record(**arguments)
            elif tool_name == 'create_record':
                return self._create_record(view_context=view_context, **arguments)
            elif tool_name == 'write_record':
                return self._write_record(**arguments)
            elif tool_name == 'get_model_fields':
                return self._get_model_fields(**arguments)
            elif tool_name == 'generate_graph':
                _logger.info(f"[MCP] generate_graph called with arguments: {arguments}")
                result = self._generate_graph(**arguments)
                image_base64 = result.get('image_base64') or ''
                _logger.info(f"[MCP] generate_graph result summary: success={result.get('success')}, has_image={bool(image_base64)}, image_length={len(image_base64)}")
                return result
            elif tool_name == 'create_vendor_bill_from_pdf':
                return self._create_vendor_bill_from_pdf(**arguments)
            elif tool_name == 'process_pdf_invoice':
                return self._process_pdf_invoice(**arguments)
            elif tool_name == 'create_activity':
                return self._create_activity(view_context=view_context, **arguments)
            elif tool_name == 'read_group':
                return self._read_group(**arguments)
            elif tool_name == 'debug_test_charts':
                return self.debug_test_chart_generation()
            else:
                return {'error': f'Unknown tool: {tool_name}'}
        except Exception as e:
            _logger.exception(f"Error executing MCP tool {tool_name}")
            return {'error': str(e)}

    def _search_records(self, model: str, domain: List = None, fields: List = None, limit: int = 10) -> Dict:
        """Search for records in a model"""
        try:
            import json
            _logger.info(f"[MCP] _search_records called: model={model}, domain={domain}, fields={fields}, limit={limit}")
            
            Model = self.env[model]
            domain = domain or []

            # Handle domain as string (AI sometimes sends JSON strings)
            if isinstance(domain, str):
                try:
                    # First try to fix common issues: replace Python tuples with JSON arrays
                    # Convert ("field", "op", "value") to ["field", "op", "value"]
                    fixed_domain = domain.replace('("', '["').replace('")', '"]').replace("('", '["').replace("')", '"]')
                    domain = json.loads(fixed_domain)
                    _logger.info(f"[MCP] Parsed domain from string: {domain}")
                except json.JSONDecodeError:
                    error_msg = f'Invalid domain format: {domain}'
                    _logger.error(f"[MCP] {error_msg}")
                    return {'success': False, 'error': error_msg}

            # Handle fields as string
            if isinstance(fields, str):
                try:
                    fields = json.loads(fields)
                    _logger.info(f"[MCP] Parsed fields from string: {fields}")
                except json.JSONDecodeError:
                    error_msg = f'Invalid fields format: {fields}'
                    _logger.error(f"[MCP] {error_msg}")
                    return {'success': False, 'error': error_msg}

            _logger.info(f"[MCP] Searching {model} with domain {domain}, limit {limit}")
            records = Model.search(domain, limit=limit)
            _logger.info(f"[MCP] Found {len(records)} records")

            if fields:
                data = records.read(fields)
            else:
                data = records.read()

            result = {
                'success': True,
                'count': len(data),
                'records': self._sanitize_for_json(data)
            }
            _logger.info(f"[MCP] _search_records returning success with {len(data)} records")
            return result
        except KeyError as e:
            error_msg = f"Model '{model}' not found. The required module may not be installed."
            _logger.error(f"[MCP] {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            error_msg = str(e)
            _logger.error(f"[MCP] _search_records exception: {error_msg}")
            return {'success': False, 'error': error_msg}

    def _read_record(self, model: str, record_id: int, fields: List = None) -> Dict:
        """Read a specific record"""
        try:
            Model = self.env[model]
            record = Model.browse(record_id)

            if not record.exists():
                return {'success': False, 'error': 'Record not found'}

            if fields:
                data = record.read(fields)[0]
            else:
                data = record.read()[0]

            return {
                'success': True,
                'record': self._sanitize_for_json(data)
            }
        except KeyError as e:
            return {
                'success': False,
                'error': f"Model '{model}' not found. The required module may not be installed."
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _resolve_template_variables(self, values: Dict, view_context: Optional[Dict] = None) -> Dict:
        """Resolve template variables in values dict

        Supports variables like:
        - {{uid}} -> current user ID
        - {{today}} -> today's date
        - {{next_week_monday}} -> next Monday's date
        - {{now}} -> current datetime
        - {{partner_id}} -> partner ID from view context (if available)
        - {{res_id}} -> record ID from view context (if available)
        """
        import re
        from datetime import datetime, timedelta

        # Calculate common date values
        today = datetime.now().date()
        now = datetime.now()

        # Find next Monday
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7  # If today is Monday, get next Monday
        next_monday = today + timedelta(days=days_until_monday)

        # Template variable mappings
        templates = {
            'uid': self.env.uid,
            'today': today.isoformat(),
            'tomorrow': (today + timedelta(days=1)).isoformat(),
            'next_week_monday': next_monday.isoformat(),
            'next_monday': next_monday.isoformat(),
            'now': now.isoformat(),
        }

        # Add view context variables if available
        if view_context:
            _logger.info(f"[Template Resolution] View context provided: {view_context}")
            # Check if context is recent (within last 5 minutes)
            import time
            timestamp = view_context.get('timestamp', 0)
            current_time_ms = time.time() * 1000
            age_ms = current_time_ms - timestamp if timestamp else 999999

            _logger.info(f"[Template Resolution] Context age: {age_ms / 1000:.1f}s (max: 300s)")

            if timestamp and age_ms <= 300000:  # 5 minutes
                model = view_context.get('model')
                active_id = view_context.get('active_id')

                _logger.info(f"[Template Resolution] Context is fresh: model={model}, active_id={active_id}")

                if active_id:
                    templates['res_id'] = active_id
                    templates['active_id'] = active_id

                    # If viewing a partner, make partner_id available
                    if model == 'res.partner':
                        templates['partner_id'] = active_id
                        _logger.info(f"[Template Resolution] Set partner_id={active_id} from res.partner context")
                    # If viewing other records, try to get their partner_id
                    elif model and active_id:
                        try:
                            record = self.env[model].sudo().browse(active_id)
                            if record.exists() and hasattr(record, 'partner_id'):
                                if record.partner_id:
                                    templates['partner_id'] = record.partner_id.id
                                    _logger.info(f"[Template Resolution] Extracted partner_id={record.partner_id.id} from {model} record")
                        except Exception as e:
                            _logger.debug(f"Could not extract partner_id from {model} record: {e}")
            else:
                _logger.warning(f"[Template Resolution] Context is stale or missing timestamp")
        else:
            _logger.info(f"[Template Resolution] No view context provided to template resolver")

        # Common activity type IDs (if they exist)
        try:
            call_activity = self.env['mail.activity.type'].sudo().search([
                '|', ('name', 'ilike', 'call'), ('name', 'ilike', 'phone')
            ], limit=1)
            if call_activity:
                templates['activity_type_id_for_call'] = call_activity.id
        except Exception:
            pass

        _logger.info(f"[Template Resolution] Available template variables: {list(templates.keys())}")

        def resolve_value(value):
            """Recursively resolve template variables in value"""
            if isinstance(value, str):
                # Check if entire string is a template variable
                match = re.match(r'^\{\{(\w+)\}\}$', value)
                if match:
                    var_name = match.group(1)
                    if var_name in templates:
                        return templates[var_name]
                    else:
                        raise ValueError(f"Unknown template variable: {{{{{var_name}}}}}")

                # Replace template variables within string
                def replace_template(match):
                    var_name = match.group(1)
                    if var_name in templates:
                        return str(templates[var_name])
                    else:
                        raise ValueError(f"Unknown template variable: {{{{{var_name}}}}}")

                return re.sub(r'\{\{(\w+)\}\}', replace_template, value)

            elif isinstance(value, dict):
                return {k: resolve_value(v) for k, v in value.items()}

            elif isinstance(value, list):
                return [resolve_value(v) for v in value]

            else:
                return value

        return resolve_value(values)

    def _convert_one2many_fields(self, Model, values: Dict) -> Dict:
        """Convert One2many field values to proper Odoo format.

        AI models often pass One2many fields as simple lists of dicts:
            {'invoice_line_ids': [{'product_id': 1, 'quantity': 3}]}

        Odoo requires the special command format:
            {'invoice_line_ids': [(0, 0, {'product_id': 1, 'quantity': 3})]}

        Where (0, 0, vals) means "create new record with vals"
        """
        from odoo import fields as odoo_fields

        converted_values = {}

        for field_name, value in values.items():
            if field_name not in Model._fields:
                converted_values[field_name] = value
                continue

            field = Model._fields[field_name]

            # Check if this is a One2many or Many2many field
            if isinstance(field, (odoo_fields.One2many, odoo_fields.Many2many)):
                if isinstance(value, list) and value:
                    converted_list = []
                    for item in value:
                        if isinstance(item, dict):
                            # Convert dict to (0, 0, dict) format for creation
                            converted_list.append((0, 0, item))
                        elif isinstance(item, (list, tuple)) and len(item) >= 2:
                            # Already in command format (e.g., (0, 0, {...}) or (4, id, 0))
                            converted_list.append(tuple(item))
                        elif isinstance(item, int):
                            # Just an ID - use (4, id, 0) to link existing record
                            converted_list.append((4, item, 0))
                        else:
                            converted_list.append(item)

                    converted_values[field_name] = converted_list
                    _logger.info(f"[create_record] Converted One2many field '{field_name}': {len(converted_list)} items")
                else:
                    converted_values[field_name] = value
            else:
                converted_values[field_name] = value

        return converted_values

    def _create_record(self, model: str, values, view_context: Optional[Dict] = None) -> Dict:
        """Create a new record"""
        try:
            # Check user permissions FIRST before any processing
            permission_check = self._check_user_permissions(model, 'create')
            if not permission_check['allowed']:
                _logger.warning(f"[create_record] Permission denied: {permission_check['error']}")
                return {
                    'success': False,
                    'error': permission_check['error'],
                    'permission_denied': True,
                    'details': permission_check.get('details', {})
                }

            # Handle case where values is passed as a JSON string instead of dict
            if isinstance(values, str):
                _logger.info(f"values received as string, parsing JSON: {values[:100]}...")
                try:
                    # Preprocess: Quote unquoted template variables for valid JSON
                    # This handles cases like: "user_id": {{uid}} -> "user_id": "{{uid}}"
                    import re
                    values = re.sub(r':\s*\{\{(\w+)\}\}', r': "{{\1}}"', values)
                    _logger.info(f"After preprocessing template variables: {values[:100]}...")

                    values = json.loads(values)
                except json.JSONDecodeError as e:
                    return {
                        'success': False,
                        'error': f"Invalid JSON in values parameter: {str(e)}. Values must be a valid JSON object."
                    }

            if not isinstance(values, dict):
                return {
                    'success': False,
                    'error': f"values must be a dict/object, got {type(values).__name__}"
                }

            # Resolve any template variables in values
            try:
                _logger.info(f"[create_record] Before template resolution, values: {values}")
                _logger.info(f"[create_record] View context available: {bool(view_context)}")
                values = self._resolve_template_variables(values, view_context=view_context)
                _logger.info(f"[create_record] After template resolution, values: {values}")
            except ValueError as e:
                return {
                    'success': False,
                    'error': f"Template variable error: {str(e)}"
                }

            Model = self.env[model]

            # Filter out invalid fields to prevent errors
            # Get valid field names for this model
            valid_fields = set(Model._fields.keys())
            invalid_fields = []
            filtered_values = {}

            for key, value in values.items():
                if key in valid_fields:
                    filtered_values[key] = value
                else:
                    invalid_fields.append(key)

            if invalid_fields:
                _logger.warning(f"[create_record] Filtered out invalid fields for {model}: {invalid_fields}")

            values = filtered_values

            # Special handling for mail.activity - need to convert res_model to res_model_id
            if model == 'mail.activity' and 'res_model' in values and 'res_model_id' not in values:
                res_model_name = values.get('res_model')
                ir_model = self.env['ir.model'].sudo().search([('model', '=', res_model_name)], limit=1)
                if ir_model:
                    values['res_model_id'] = ir_model.id
                else:
                    return {
                        'success': False,
                        'error': f"Model '{res_model_name}' not found in ir.model. Cannot create activity."
                    }

            # Convert One2many fields to proper Odoo format
            # AI might pass: {'invoice_line_ids': [{'product_id': 1, 'quantity': 3}]}
            # Odoo requires: {'invoice_line_ids': [(0, 0, {'product_id': 1, 'quantity': 3})]}
            values = self._convert_one2many_fields(Model, values)

            # Use savepoint to handle database errors gracefully
            # This prevents UniqueViolation and other DB errors from aborting the whole transaction
            import psycopg2
            savepoint_name = f"create_record_{model.replace('.', '_')}_{id(values)}"

            try:
                self.env.cr.execute(f'SAVEPOINT {savepoint_name}')
                record = Model.create(values)
                self.env.cr.execute(f'RELEASE SAVEPOINT {savepoint_name}')

                return {
                    'success': True,
                    'record_id': record.id,
                    'record': self._sanitize_for_json(record.read()[0])
                }
            except psycopg2.errors.UniqueViolation as e:
                # Rollback to savepoint to recover the transaction
                self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {savepoint_name}')
                self.env.cr.execute(f'RELEASE SAVEPOINT {savepoint_name}')
                _logger.warning(f"[create_record] Duplicate record in {model}: {e}")
                # Extract the key name for a more helpful error message
                error_msg = str(e)
                if 'already exists' in error_msg:
                    return {
                        'success': False,
                        'error': f"A record with these values already exists in {model}. Try searching for existing records first or use a different value."
                    }
                return {'success': False, 'error': f"Duplicate record: {str(e)}"}
            except psycopg2.Error as e:
                # Handle other database errors
                self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {savepoint_name}')
                self.env.cr.execute(f'RELEASE SAVEPOINT {savepoint_name}')
                _logger.exception(f"Database error creating record in model {model}")
                return {'success': False, 'error': f"Database error: {str(e)}"}

        except KeyError as e:
            # Model doesn't exist - likely module not installed
            return {
                'success': False,
                'error': f"Model '{model}' not found. The required module may not be installed. Please check if the module is installed and activated."
            }
        except Exception as e:
            _logger.exception(f"Error creating record in model {model}")
            return {'success': False, 'error': str(e)}

    def _write_record(self, model: str, record_id: int, values: Dict) -> Dict:
        """Update an existing record"""
        import psycopg2
        try:
            # Check user permissions FIRST - both model-level and record-level
            permission_check = self._check_user_permissions(model, 'write', record_id=record_id)
            if not permission_check['allowed']:
                _logger.warning(f"[write_record] Permission denied: {permission_check['error']}")
                return {
                    'success': False,
                    'error': permission_check['error'],
                    'permission_denied': True,
                    'details': permission_check.get('details', {})
                }

            Model = self.env[model]
            record = Model.browse(record_id)

            if not record.exists():
                return {'success': False, 'error': 'Record not found'}

            # Use savepoint to handle database errors gracefully
            savepoint_name = f"write_record_{model.replace('.', '_')}_{record_id}"

            try:
                self.env.cr.execute(f'SAVEPOINT {savepoint_name}')
                record.write(values)
                self.env.cr.execute(f'RELEASE SAVEPOINT {savepoint_name}')

                return {
                    'success': True,
                    'record': self._sanitize_for_json(record.read()[0])
                }
            except psycopg2.errors.UniqueViolation as e:
                self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {savepoint_name}')
                self.env.cr.execute(f'RELEASE SAVEPOINT {savepoint_name}')
                _logger.warning(f"[write_record] Duplicate value in {model}: {e}")
                return {
                    'success': False,
                    'error': f"Cannot update: a record with these values already exists. Try a different value."
                }
            except psycopg2.Error as e:
                self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {savepoint_name}')
                self.env.cr.execute(f'RELEASE SAVEPOINT {savepoint_name}')
                _logger.exception(f"Database error updating record in model {model}")
                return {'success': False, 'error': f"Database error: {str(e)}"}

        except KeyError as e:
            return {
                'success': False,
                'error': f"Model '{model}' not found. The required module may not be installed."
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _get_model_fields(self, model: str) -> Dict:
        """Get field information for a model"""
        try:
            Model = self.env[model]
            fields_info = Model.fields_get()

            return {
                'success': True,
                'model': model,
                'fields': fields_info
            }
        except KeyError as e:
            return {
                'success': False,
                'error': f"Model '{model}' not found. The required module may not be installed."
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _read_group(self, model: str, groupby: List[str], domain: List = None,
                    fields: List[str] = None, orderby: str = '', limit: int = 80) -> Dict:
        """Aggregate and group records from an Odoo model"""
        try:
            import json
            Model = self.env[model]
            domain = domain or []
            fields = fields or []

            # Handle domain as string (AI sometimes sends JSON strings)
            if isinstance(domain, str):
                try:
                    # First try to fix common issues: replace Python tuples with JSON arrays
                    # Convert ("field", "op", "value") to ["field", "op", "value"]
                    fixed_domain = domain.replace('("', '["').replace('")', '"]').replace("('", '["').replace("')", '"]')
                    domain = json.loads(fixed_domain)
                except json.JSONDecodeError:
                    return {'success': False, 'error': f'Invalid domain format: {domain}'}

            # Handle fields as string
            if isinstance(fields, str):
                try:
                    fields = json.loads(fields)
                except json.JSONDecodeError:
                    return {'success': False, 'error': f'Invalid fields format: {fields}'}

            # Handle groupby as string
            if isinstance(groupby, str):
                try:
                    groupby = json.loads(groupby)
                except json.JSONDecodeError:
                    # Try treating it as a single field name
                    groupby = [groupby]

            # Ensure groupby is a list
            if not isinstance(groupby, list):
                groupby = [groupby]

            # Call Odoo's read_group method
            result = Model.read_group(
                domain=domain,
                fields=fields,
                groupby=groupby,
                orderby=orderby if orderby else False,
                limit=limit if limit else None,
                lazy=False  # Get all groupby levels at once
            )

            return {
                'success': True,
                'count': len(result),
                'groups': self._sanitize_for_json(result)
            }
        except KeyError as e:
            return {
                'success': False,
                'error': f"Model '{model}' not found. The required module may not be installed."
            }
        except Exception as e:
            _logger.exception(f"Error in read_group for model {model}")
            return {'success': False, 'error': str(e)}

    def _generate_graph(self, graph_type: str, model: str, y_field: str,
                       x_field: str = None, domain: List = None,
                       group_by: str = None, title: str = None,
                       date_range: str = 'month', aggregation: str = 'sum',
                       limit: int = 50) -> Dict:
        """Generate graph data from Odoo records"""
        _logger.info(f"[Graph] Generating {graph_type} chart for {model}")
        _logger.info(f"[Graph] Parameters: x_field={x_field}, y_field={y_field}, group_by={group_by}, domain={domain}")
        
        # Warn if group_by is missing - this is usually the cause of identical charts
        if not group_by:
            _logger.warning(f"[Graph] WARNING: group_by is None! This will create a single 'Total' bar instead of grouped data. For meaningful charts, specify group_by parameter.")
        
        try:
            import json
            Model = self.env[model]

            # Handle domain as string (AI sometimes sends JSON strings)
            if isinstance(domain, str):
                try:
                    # First try to fix common issues: replace Python tuples with JSON arrays
                    # Convert ("field", "op", "value") to ["field", "op", "value"]
                    fixed_domain = domain.replace('("', '["').replace('")', '"]').replace("('", '["').replace("')", '"]')
                    domain = json.loads(fixed_domain)
                    _logger.info(f"[Graph] Parsed domain from string: {domain}")
                except json.JSONDecodeError:
                    error_msg = f'Invalid domain format: {domain}'
                    _logger.error(f"[Graph] {error_msg}")
                    return {'success': False, 'error': error_msg}

            # Apply date range to domain if x_field is a date field
            if x_field and domain is None:
                domain = []
            elif domain is None:
                domain = []

            if x_field:
                # Check if x_field is a date field
                try:
                    field_info = Model.fields_get([x_field])
                    if x_field in field_info and field_info[x_field]['type'] in ['date', 'datetime']:
                        if date_range != 'all':
                            days_map = {'week': 7, 'month': 30, 'quarter': 90, 'year': 365}
                            days = days_map.get(date_range, 30)
                            cutoff_date = datetime.now() - timedelta(days=days)
                            domain.append((x_field, '>=', cutoff_date.strftime('%Y-%m-%d')))
                except Exception:
                    pass

            # Fetch records
            records = Model.search(domain, limit=limit * 2)  # Fetch more for grouping
            _logger.info(f"[Graph] Found {len(records)} records matching domain: {domain}")

            if not records:
                return {'success': False, 'error': 'No records found matching the criteria'}

            # Read data
            fields_to_read = [y_field]
            if x_field:
                fields_to_read.append(x_field)
            if group_by:
                fields_to_read.append(group_by)

            _logger.info(f"[Graph] Reading fields: {fields_to_read}")
            data = records.read(fields_to_read)
            _logger.info(f"[Graph] Read {len(data)} records, sample data: {data[:2] if len(data) >= 2 else data}")

            # Process data based on graph type and grouping
            # Use pure Python implementation (lightweight, no dependencies)
            # Generate title if not provided
            if not title:
                title = self._generate_title(model, y_field, group_by, aggregation)

            result = self._process_graph_data(
                data, graph_type, x_field, y_field, group_by, aggregation, limit, title
            )

            # Add metadata
            result['graph_data']['title'] = title
            result['graph_data']['record_count'] = len(records)
            
            _logger.info(f"[Graph] Final chart data - labels: {result['graph_data'].get('labels', [])[:5]}, values: {result['graph_data'].get('datasets', [{}])[0].get('data', [])[:5]}")

            return result

        except Exception as e:
            _logger.exception("Error generating graph")
            return {'success': False, 'error': str(e)}

    def _process_graph_data(self, data: List[Dict], graph_type: str,
                            x_field: str, y_field: str, group_by: str,
                            aggregation: str, limit: int, title: str) -> Dict:
        """Process graph data using pure Python (lightweight, no dependencies)"""
        _logger.info(f"[Graph] Processing data - group_by={group_by}, y_field={y_field}, aggregation={aggregation}")
        # Simple implementation without pandas
        if group_by:
            # Group and aggregate manually
            groups = {}
            for record in data:
                key = self._format_label(record.get(group_by))
                value = float(record.get(y_field, 0)) if record.get(y_field) is not None else 0

                if key not in groups:
                    groups[key] = []
                groups[key].append(value)

            _logger.info(f"[Graph] Groups formed: {dict(list(groups.items())[:3])}")  # Show first 3 groups

            # Apply aggregation
            result_data = {}
            for key, values in groups.items():
                if aggregation == 'count':
                    result_data[key] = len(values)
                elif aggregation == 'avg':
                    result_data[key] = sum(values) / len(values) if values else 0
                elif aggregation == 'min':
                    result_data[key] = min(values) if values else 0
                elif aggregation == 'max':
                    result_data[key] = max(values) if values else 0
                else:  # sum
                    result_data[key] = sum(values)

            # Sort and limit
            sorted_items = sorted(result_data.items(), key=lambda x: x[1], reverse=True)[:limit]
            labels = [item[0] for item in sorted_items]
            values = [item[1] for item in sorted_items]

        else:
            # Simple aggregation
            all_values = [float(record.get(y_field, 0)) if record.get(y_field) is not None else 0
                         for record in data]

            if aggregation == 'count':
                value = len(all_values)
            elif aggregation == 'avg':
                value = sum(all_values) / len(all_values) if all_values else 0
            elif aggregation == 'min':
                value = min(all_values) if all_values else 0
            elif aggregation == 'max':
                value = max(all_values) if all_values else 0
            else:  # sum
                value = sum(all_values)

            labels = ['Total']
            values = [value]

        # Generate actual image for embedding in Discuss
        _logger.info(f"[Graph] Rendering image with labels: {labels}, values: {values}")
        image_base64 = self._render_graph_image(graph_type, labels, values, title)

        return {
            'success': True,
            'image_base64': image_base64,
            'graph_data': {
                'type': graph_type,
                'labels': labels,
                'datasets': [{
                    'label': y_field.replace('_', ' ').title(),
                    'data': values
                }]
            }
        }

    def _render_graph_image(self, graph_type: str, labels: List, values: List, title: str,
                            stacked_data: Dict = None, show_values: bool = True) -> str:
        """
        Render graph as base64 encoded image with value labels and stacked chart support.

        Args:
            graph_type: Type of chart (bar, line, pie, stacked_bar, horizontal_bar)
            labels: X-axis labels
            values: Y-axis values (single series)
            title: Chart title
            stacked_data: Dict for stacked charts: {'series_names': [...], 'series_data': [[...], [...]]}
            show_values: Whether to show value labels on charts
        """
        try:
            import matplotlib
            matplotlib.use('Agg')  # Non-interactive backend
            import matplotlib.pyplot as plt
            import base64
            from io import BytesIO

            # Odoo-style colors palette
            colors = ['#875A7B', '#00A09D', '#F06050', '#F4A460', '#6CC3D5',
                      '#7C7BAD', '#E6C74C', '#97D077', '#B37D4E', '#5B899E']

            # Create figure with appropriate size
            fig_width = max(10, len(labels) * 0.8) if labels else 10
            fig, ax = plt.subplots(figsize=(min(fig_width, 16), 7))

            def format_value(val):
                """Format value for display (with thousands separator)"""
                if val >= 1000000:
                    return f'{val/1000000:,.1f}M'
                elif val >= 1000:
                    return f'{val/1000:,.1f}K'
                elif isinstance(val, float):
                    return f'{val:,.2f}'
                else:
                    return f'{val:,}'

            if graph_type == 'bar' or graph_type == 'column':
                bars = ax.bar(range(len(labels)), values, color=colors[0], edgecolor='white', linewidth=0.5)
                ax.set_xticks(range(len(labels)))
                ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=9)

                # Add value labels on top of bars
                if show_values:
                    for bar, val in zip(bars, values):
                        height = bar.get_height()
                        ax.annotate(format_value(val),
                                    xy=(bar.get_x() + bar.get_width() / 2, height),
                                    xytext=(0, 3), textcoords="offset points",
                                    ha='center', va='bottom', fontsize=8, fontweight='bold')

            elif graph_type == 'horizontal_bar' or graph_type == 'hbar':
                bars = ax.barh(range(len(labels)), values, color=colors[0], edgecolor='white', linewidth=0.5)
                ax.set_yticks(range(len(labels)))
                ax.set_yticklabels(labels, fontsize=9)

                # Add value labels at end of bars
                if show_values:
                    for bar, val in zip(bars, values):
                        width = bar.get_width()
                        ax.annotate(format_value(val),
                                    xy=(width, bar.get_y() + bar.get_height() / 2),
                                    xytext=(3, 0), textcoords="offset points",
                                    ha='left', va='center', fontsize=8, fontweight='bold')

            elif graph_type == 'stacked_bar' or graph_type == 'stacked' or graph_type == 'piled':
                # Stacked/piled column chart
                if stacked_data and 'series_data' in stacked_data:
                    series_names = stacked_data.get('series_names', [f'Series {i+1}' for i in range(len(stacked_data['series_data']))])
                    series_data = stacked_data['series_data']
                    x = range(len(labels))
                    bottom = [0] * len(labels)

                    for idx, (series_vals, name) in enumerate(zip(series_data, series_names)):
                        color = colors[idx % len(colors)]
                        bars = ax.bar(x, series_vals, bottom=bottom, label=name,
                                      color=color, edgecolor='white', linewidth=0.5)

                        # Add value labels inside bars (if significant)
                        if show_values:
                            for bar, val in zip(bars, series_vals):
                                if val > 0:
                                    height = bar.get_height()
                                    if height > max(values) * 0.05:  # Only show if bar is big enough
                                        ax.annotate(format_value(val),
                                                    xy=(bar.get_x() + bar.get_width() / 2,
                                                        bar.get_y() + height / 2),
                                                    ha='center', va='center', fontsize=7,
                                                    color='white', fontweight='bold')

                        # Update bottom for next series
                        bottom = [b + v for b, v in zip(bottom, series_vals)]

                    # Add total labels on top
                    if show_values:
                        for i, total in enumerate(bottom):
                            ax.annotate(format_value(total),
                                        xy=(i, total), xytext=(0, 3),
                                        textcoords="offset points",
                                        ha='center', va='bottom', fontsize=8, fontweight='bold')

                    ax.legend(loc='upper right', fontsize=8)
                else:
                    # Fallback to regular bar if no stacked data
                    bars = ax.bar(range(len(labels)), values, color=colors[0])

                ax.set_xticks(range(len(labels)))
                ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=9)

            elif graph_type == 'line':
                line, = ax.plot(range(len(labels)), values, marker='o', color=colors[0],
                                linewidth=2, markersize=6, markerfacecolor='white', markeredgewidth=2)
                ax.set_xticks(range(len(labels)))
                ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=9)

                # Add value labels above points
                if show_values:
                    for i, val in enumerate(values):
                        ax.annotate(format_value(val),
                                    xy=(i, val), xytext=(0, 8),
                                    textcoords="offset points",
                                    ha='center', va='bottom', fontsize=8, fontweight='bold')

                # Fill area under line
                ax.fill_between(range(len(labels)), values, alpha=0.3, color=colors[0])

            elif graph_type == 'pie':
                # Calculate total for center annotation
                total = sum(values)

                # Create pie with percentages and values
                def make_autopct(values):
                    def my_autopct(pct):
                        val = int(round(pct * total / 100.0))
                        return f'{pct:.1f}%\n({format_value(val)})'
                    return my_autopct

                wedges, texts, autotexts = ax.pie(
                    values, labels=labels, autopct=make_autopct(values),
                    startangle=90, colors=colors[:len(values)],
                    explode=[0.02] * len(values),  # Slight separation
                    shadow=False, textprops={'fontsize': 8}
                )

                # Style the percentage text
                for autotext in autotexts:
                    autotext.set_fontsize(7)
                    autotext.set_fontweight('bold')

                # Add total in the center (for donut effect, uncomment circle)
                # centre_circle = plt.Circle((0, 0), 0.50, fc='white')
                # ax.add_patch(centre_circle)
                ax.annotate(f'Total: {format_value(total)}',
                            xy=(0, -1.3), ha='center', fontsize=10, fontweight='bold')

            elif graph_type == 'donut':
                total = sum(values)

                def make_autopct(values):
                    def my_autopct(pct):
                        val = int(round(pct * total / 100.0))
                        return f'{pct:.1f}%'
                    return my_autopct

                wedges, texts, autotexts = ax.pie(
                    values, labels=labels, autopct=make_autopct(values),
                    startangle=90, colors=colors[:len(values)],
                    pctdistance=0.75, textprops={'fontsize': 8}
                )

                # Create donut effect
                centre_circle = plt.Circle((0, 0), 0.55, fc='white')
                ax.add_patch(centre_circle)

                # Add total in center
                ax.annotate(f'Total\n{format_value(total)}',
                            xy=(0, 0), ha='center', va='center',
                            fontsize=12, fontweight='bold')

            else:  # default to bar
                bars = ax.bar(range(len(labels)), values, color=colors[0], edgecolor='white')
                ax.set_xticks(range(len(labels)))
                ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=9)

                if show_values:
                    for bar, val in zip(bars, values):
                        height = bar.get_height()
                        ax.annotate(format_value(val),
                                    xy=(bar.get_x() + bar.get_width() / 2, height),
                                    xytext=(0, 3), textcoords="offset points",
                                    ha='center', va='bottom', fontsize=8, fontweight='bold')

            # Style the chart
            ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)

            # Add gridlines for non-pie charts
            if graph_type not in ['pie', 'donut']:
                ax.yaxis.grid(True, linestyle='--', alpha=0.7)
                ax.set_axisbelow(True)

            plt.tight_layout()

            # Convert to base64
            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=120, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            buffer.seek(0)
            image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
            plt.close(fig)

            return image_base64

        except ImportError:
            _logger.warning("matplotlib not available, graphs will not be rendered")
            return None
        except Exception as e:
            _logger.error(f"Error rendering graph: {e}", exc_info=True)
            return None

    def _format_label(self, label) -> str:
        """Format a label for display"""
        if isinstance(label, (list, tuple)) and len(label) > 1:
            # Many2one field
            return str(label[1])
        elif isinstance(label, datetime):
            return label.strftime('%Y-%m-%d')
        elif label is None or label is False:
            return 'N/A'
        else:
            return str(label)

    def debug_test_chart_generation(self):
        """Test chart generation with different parameters"""
        _logger.info("[DEBUG] Testing chart generation with different parameters...")
        
        # Test 1: Sale orders by state
        test1 = self._generate_graph(
            graph_type='pie',
            model='sale.order',
            y_field='amount_total',
            group_by='state',
            aggregation='sum',
            title='Sales by State'
        )
        _logger.info(f"[DEBUG] Test 1 (by state): success={test1.get('success')}, image_size={len(test1.get('image_base64') or '')}")
        
        # Test 2: Sale orders by customer
        test2 = self._generate_graph(
            graph_type='bar',
            model='sale.order',
            y_field='amount_total',
            group_by='partner_id',
            aggregation='sum',
            limit=10,
            title='Top 10 Customers'
        )
        _logger.info(f"[DEBUG] Test 2 (by customer): success={test2.get('success')}, image_size={len(test2.get('image_base64') or '')}")
        
        return {"test1_size": len(test1.get('image_base64') or ''), "test2_size": len(test2.get('image_base64') or '')}

    def _process_pdf_invoice(self, attachment_id: int, filename: str = None) -> Dict:
        """Process PDF invoice from attachment and create vendor bill"""
        try:
            # Check user permissions for creating vendor bills (account.move)
            permission_check = self._check_user_permissions('account.move', 'create')
            if not permission_check['allowed']:
                _logger.warning(f"[process_pdf_invoice] Permission denied: {permission_check['error']}")
                return {
                    'success': False,
                    'error': permission_check['error'],
                    'permission_denied': True,
                    'details': permission_check.get('details', {})
                }

            from .pdf_processor import PDFInvoiceProcessor

            # Get attachment
            Attachment = self.env['ir.attachment']
            attachment = Attachment.browse(attachment_id)
            
            if not attachment.exists():
                return {
                    'success': False,
                    'error': f'Attachment with ID {attachment_id} not found'
                }
            
            # Try to access attachment data with proper error handling
            try:
                attachment_data = attachment.datas
                if not attachment_data:
                    return {
                        'success': False,
                        'error': 'Attachment has no content'
                    }
            except FileNotFoundError as e:
                return {
                    'success': False,
                    'error': f'Attachment file not found in filestore: {str(e)}. The file may have been deleted or moved.'
                }
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Error accessing attachment data: {str(e)}'
                }
            
            # Decode PDF content
            import base64
            try:
                pdf_content = base64.b64decode(attachment_data)
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Error decoding attachment data: {str(e)}'
                }
            filename = filename or attachment.name
            
            # Process PDF with OCR
            processor = PDFInvoiceProcessor(self.env)
            result = processor.process_pdf(pdf_content, filename)
            
            if not result['success']:
                return result
            
            # Create vendor bill
            bill_result = processor.create_vendor_bill(
                invoice_data=result['data'],
                pdf_content_b64=attachment_data,
                filename=filename
            )
            
            if bill_result.get('success') or bill_result.get('partial_success'):
                # Return the full result including partial success info
                response = {
                    'success': bill_result.get('success', False),
                    'partial_success': bill_result.get('partial_success', False),
                    'invoice_id': bill_result.get('invoice_id'),
                    'invoice_name': bill_result.get('invoice_name'),
                    'vendor_name': bill_result.get('vendor_name'),
                    'total': bill_result.get('total', 0),
                    'currency': bill_result.get('currency'),
                    'lines_processed': bill_result.get('lines_processed', 0),
                    'lines_needing_review': bill_result.get('lines_needing_review', 0),
                    'match_summary': bill_result.get('match_summary', {}),
                    'message': bill_result.get('message', ''),
                    'ocr_method': result.get('ocr_method', 'text-based'),
                    'extracted_text_length': len(result.get('raw_text') or '')
                }

                # Add warnings if any
                if bill_result.get('warnings'):
                    response['warnings'] = bill_result['warnings']

                return response
            else:
                return bill_result
                
        except Exception as e:
            _logger.exception("Error processing PDF invoice")
            return {'success': False, 'error': str(e)}

    def _create_activity(self, res_model: str = None, res_id: int = None, summary: str = None,
                        note: str = None, activity_type: str = 'todo', due_days: int = 1,
                        view_context: Optional[Dict] = None) -> Dict:
        """Create an activity/reminder for a record"""
        _logger.info(f"[Create Activity] Called with: res_model={res_model}, res_id={res_id}, summary={summary}")
        _logger.info(f"[Create Activity] View context available: {bool(view_context)}")
        if view_context:
            _logger.info(f"[Create Activity] View context contents: {view_context}")
        try:
            # Check user permissions for creating activities (mail.activity)
            permission_check = self._check_user_permissions('mail.activity', 'create')
            if not permission_check['allowed']:
                _logger.warning(f"[create_activity] Permission denied: {permission_check['error']}")
                return {
                    'success': False,
                    'error': permission_check['error'],
                    'permission_denied': True,
                    'details': permission_check.get('details', {})
                }
            # If view context is available and parameters are missing, use context to fill them
            if view_context and (not res_model or not res_id):
                if not res_model:
                    res_model = view_context.get('model', 'res.partner')
                if not res_id:
                    res_id = view_context.get('active_id')
                    
                _logger.info(f"[Create Activity] Using view context: model={res_model}, res_id={res_id}")
            
            # Validate required parameters
            if not res_model or not res_id or not summary:
                missing = []
                if not res_model:
                    missing.append('res_model')
                if not res_id:
                    missing.append('res_id') 
                if not summary:
                    missing.append('summary')
                return {
                    'success': False,
                    'error': f'Missing required parameters: {", ".join(missing)}. Use view context or provide explicitly.'
                }
            # Map activity types to Odoo activity type IDs
            ActivityType = self.env['mail.activity.type']
            
            # Try to find the right activity type
            type_mapping = {
                'call': ['call', 'phone'],
                'meeting': ['meeting'],
                'todo': ['todo', 'to do', 'task'],
                'email': ['email', 'mail'],
                'follow_up': ['follow', 'followup']
            }
            
            activity_type_record = None
            search_terms = type_mapping.get(activity_type, [activity_type])
            
            for term in search_terms:
                activity_type_record = ActivityType.search([
                    ('name', 'ilike', term)
                ], limit=1)
                if activity_type_record:
                    break
            
            # Fallback to first available activity type
            if not activity_type_record:
                activity_type_record = ActivityType.search([], limit=1)
            
            if not activity_type_record:
                return {
                    'success': False,
                    'error': 'No activity types found in the system'
                }
            
            # Calculate due date
            from datetime import date, timedelta
            due_date = date.today() + timedelta(days=due_days)
            
            # Validate that the record exists
            try:
                _logger.info(f"[Create Activity] Checking if record exists: {res_model}({res_id})")
                target_record = self.env[res_model].browse(res_id)
                if not target_record.exists():
                    _logger.error(f"[Create Activity] Record not found: {res_model}({res_id})")
                    return {
                        'success': False,
                        'error': f'Record {res_model}({res_id}) not found'
                    }
                record_name = target_record.display_name if hasattr(target_record, 'display_name') else target_record.name
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Invalid record reference {res_model}({res_id}): {str(e)}'
                }
            
            # Create the activity
            Activity = self.env['mail.activity']

            # Get res_model_id (required by mail.activity)
            IrModel = self.env['ir.model']
            model_record = IrModel.search([('model', '=', res_model)], limit=1)
            if not model_record:
                return {
                    'success': False,
                    'error': f'Model {res_model} not found in ir.model'
                }

            activity_vals = {
                'activity_type_id': activity_type_record.id,
                'summary': summary,
                'res_id': res_id,
                'res_model_id': model_record.id,  # Use res_model_id instead of res_model
                'user_id': self.env.user.id,
                'date_deadline': due_date,
            }
            
            if note:
                activity_vals['note'] = note
            
            activity = Activity.create(activity_vals)
            
            return {
                'success': True,
                'activity_id': activity.id,
                'activity_type': activity_type_record.name,
                'due_date': due_date.strftime('%Y-%m-%d'),
                'record_name': record_name,
                'message': f"✅ Created {activity_type_record.name.lower()} activity '{summary}' for {record_name}, due on {due_date.strftime('%Y-%m-%d')}"
            }
            
        except Exception as e:
            _logger.exception("Error creating activity")
            return {
                'success': False,
                'error': str(e)
            }

    def _generate_title(self, model: str, y_field: str, group_by: str = None,
                       aggregation: str = 'sum') -> str:
        """Generate a title for the graph"""
        parts = []
        parts.append(aggregation.title())
        parts.append('of')
        parts.append(y_field.replace('_', ' ').title())

        if group_by:
            parts.append('by')
            parts.append(group_by.replace('_', ' ').title())

        parts.append(f'({model})')

        return ' '.join(parts)

    def _create_vendor_bill_from_pdf(self, invoice_data: Dict,
                                     pdf_content_b64: str = None,
                                     filename: str = None) -> Dict:
        """Create vendor bill from parsed PDF data"""
        try:
            from .pdf_processor import PDFInvoiceProcessor

            processor = PDFInvoiceProcessor(self.env)
            result = processor.create_vendor_bill(
                invoice_data=invoice_data,
                pdf_content_b64=pdf_content_b64,
                filename=filename
            )

            return result

        except Exception as e:
            _logger.exception("Error creating vendor bill from PDF")
            return {
                'success': False,
                'error': str(e)
            }


class MCPServerRegistry(models.AbstractModel):
    """Registry for MCP Server instances"""

    _name = 'mcp.server.registry'
    _description = 'MCP Server Registry'

    @api.model
    def get_server(self):
        """Get or create the MCP server instance (one per database)"""
        global _mcp_server_cache, _cache_lock

        db_name = self.env.cr.dbname

        with _cache_lock:
            if db_name not in _mcp_server_cache:
                _logger.info(f"Creating new MCP server instance for database: {db_name}")
                _mcp_server_cache[db_name] = MCPServer(self.env)
            else:
                # Refresh the environment to avoid stale cursor issues
                _mcp_server_cache[db_name].env = self.env

            return _mcp_server_cache[db_name]

    @api.model
    def list_tools(self):
        """List available MCP tools"""
        server = self.get_server()
        return server.list_tools()

    @api.model
    def call_tool(self, tool_name, arguments, view_context=None):
        """Call an MCP tool with optional view context"""
        server = self.get_server()
        return server.call_tool(tool_name, arguments, view_context=view_context)
