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
                'description': 'Search and retrieve records from any Odoo model. Use this tool for: queries, counts, sums, checking status, listing data, getting totals, finding records. Returns actual data that you can analyze and present to user. This is your PRIMARY tool for data retrieval.',
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
                'description': 'Create a new record in an Odoo model. IMPORTANT: values parameter must be a JSON object (dict), not a string. Supported template variables in values: {{uid}} (current user ID), {{today}}, {{tomorrow}}, {{next_week_monday}}, {{next_monday}}, {{now}}, {{activity_type_id_for_call}}. For other dynamic values like partner_id or res_id, extract them from context or ask the user.',
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
                'description': 'Update/modify/change existing records. Use when user asks to mark, update, change, or modify data. IMPORTANT: You MUST always provide the values parameter as a dict/object with the fields to update. Example: to mark sale order as sent, use values={"state": "sent"}. Common sale.order states: "draft", "sent", "sale", "done", "cancel".',
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
                'description': 'Generate a visual chart/graph ONLY when user explicitly asks for: "chart", "graph", "plot", "visualize", "show me a chart". DO NOT use for: sums, counts, queries, status checks, or when user just wants numbers. Use search_records instead for data queries.',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'graph_type': {
                            'type': 'string',
                            'enum': ['line', 'bar', 'pie', 'area', 'scatter', 'doughnut'],
                            'description': 'Type of graph to generate'
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
                        'x_field': {
                            'type': 'string',
                            'description': 'Field for X axis (e.g., create_date, date_order) - optional for pie charts'
                        },
                        'y_field': {
                            'type': 'string',
                            'description': 'Field for Y axis - numeric field to aggregate (e.g., amount_total, quantity)'
                        },
                        'aggregation': {
                            'type': 'string',
                            'enum': ['sum', 'avg', 'count', 'min', 'max'],
                            'description': 'Aggregation method for y_field',
                            'default': 'sum'
                        },
                        'group_by': {
                            'type': 'string',
                            'description': 'Optional field to group by (e.g., partner_id, state, user_id)'
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
                    'required': ['graph_type', 'model', 'y_field']
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
            'read_group': {
                'name': 'read_group',
                'description': 'Aggregate and group records from an Odoo model. Use this for: summing values by category, counting records by field, getting totals grouped by product/partner/date, calculating averages per group. Perfect for "sum by product", "total by customer", "count by status", etc.',
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
                return self._generate_graph(**arguments)
            elif tool_name == 'create_vendor_bill_from_pdf':
                return self._create_vendor_bill_from_pdf(**arguments)
            elif tool_name == 'read_group':
                return self._read_group(**arguments)
            else:
                return {'error': f'Unknown tool: {tool_name}'}
        except Exception as e:
            _logger.exception(f"Error executing MCP tool {tool_name}")
            return {'error': str(e)}

    def _search_records(self, model: str, domain: List = None, fields: List = None, limit: int = 10) -> Dict:
        """Search for records in a model"""
        try:
            import json
            Model = self.env[model]
            domain = domain or []

            # Handle domain as string (AI sometimes sends JSON strings)
            if isinstance(domain, str):
                try:
                    domain = json.loads(domain)
                except json.JSONDecodeError:
                    return {'success': False, 'error': f'Invalid domain format: {domain}'}

            # Handle fields as string
            if isinstance(fields, str):
                try:
                    fields = json.loads(fields)
                except json.JSONDecodeError:
                    return {'success': False, 'error': f'Invalid fields format: {fields}'}

            records = Model.search(domain, limit=limit)

            if fields:
                data = records.read(fields)
            else:
                data = records.read()

            return {
                'success': True,
                'count': len(data),
                'records': self._sanitize_for_json(data)
            }
        except KeyError as e:
            return {
                'success': False,
                'error': f"Model '{model}' not found. The required module may not be installed."
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

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

    def _create_record(self, model: str, values, view_context: Optional[Dict] = None) -> Dict:
        """Create a new record"""
        try:
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

            record = Model.create(values)

            return {
                'success': True,
                'record_id': record.id,
                'record': self._sanitize_for_json(record.read()[0])
            }
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
        try:
            Model = self.env[model]
            record = Model.browse(record_id)

            if not record.exists():
                return {'success': False, 'error': 'Record not found'}

            record.write(values)

            return {
                'success': True,
                'record': self._sanitize_for_json(record.read()[0])
            }
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
                    domain = json.loads(domain)
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
        try:
            Model = self.env[model]

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

            if not records:
                return {'success': False, 'error': 'No records found matching the criteria'}

            # Read data
            fields_to_read = [y_field]
            if x_field:
                fields_to_read.append(x_field)
            if group_by:
                fields_to_read.append(group_by)

            data = records.read(fields_to_read)

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

            return result

        except Exception as e:
            _logger.exception("Error generating graph")
            return {'success': False, 'error': str(e)}

    def _process_graph_data(self, data: List[Dict], graph_type: str,
                            x_field: str, y_field: str, group_by: str,
                            aggregation: str, limit: int, title: str) -> Dict:
        """Process graph data using pure Python (lightweight, no dependencies)"""
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

    def _render_graph_image(self, graph_type: str, labels: List, values: List, title: str) -> str:
        """Render graph as base64 encoded image"""
        try:
            import matplotlib
            matplotlib.use('Agg')  # Non-interactive backend
            import matplotlib.pyplot as plt
            import base64
            from io import BytesIO

            # Create figure
            fig, ax = plt.subplots(figsize=(10, 6))

            if graph_type == 'bar':
                ax.bar(range(len(labels)), values, color='#875A7B')
                ax.set_xticks(range(len(labels)))
                ax.set_xticklabels(labels, rotation=45, ha='right')
            elif graph_type == 'line':
                ax.plot(range(len(labels)), values, marker='o', color='#875A7B', linewidth=2)
                ax.set_xticks(range(len(labels)))
                ax.set_xticklabels(labels, rotation=45, ha='right')
            elif graph_type == 'pie':
                ax.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)
            else:  # default to bar
                ax.bar(range(len(labels)), values, color='#875A7B')
                ax.set_xticks(range(len(labels)))
                ax.set_xticklabels(labels, rotation=45, ha='right')

            ax.set_title(title, fontsize=14, fontweight='bold')
            plt.tight_layout()

            # Convert to base64
            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
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
