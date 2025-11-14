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

    def _initialize_tools(self):
        """Initialize available MCP tools"""
        self._tools = {
            'search_records': {
                'name': 'search_records',
                'description': 'Search and retrieve records from any Odoo model. Use for queries, counts, sums, checking status, and listing data. Returns actual data.',
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
                'description': 'Create a new record in an Odoo model',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string', 'description': 'The Odoo model name'},
                        'values': {'type': 'object', 'description': 'Field values for the new record'}
                    },
                    'required': ['model', 'values']
                }
            },
            'write_record': {
                'name': 'write_record',
                'description': 'Update/modify/change existing records. Use when user asks to mark, update, change, or modify data. Requires record_id and values to update.',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string', 'description': 'The Odoo model name'},
                        'record_id': {'type': 'integer', 'description': 'The record ID'},
                        'values': {'type': 'object', 'description': 'Field values to update'}
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
                'description': 'Generate a visual chart/graph ONLY when user explicitly requests visualization (chart, graph, plot). NOT for simple data queries.',
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
            }
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return list of available MCP tools"""
        return list(self._tools.values())

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an MCP tool with given arguments"""
        try:
            if tool_name == 'search_records':
                return self._search_records(**arguments)
            elif tool_name == 'read_record':
                return self._read_record(**arguments)
            elif tool_name == 'create_record':
                return self._create_record(**arguments)
            elif tool_name == 'write_record':
                return self._write_record(**arguments)
            elif tool_name == 'get_model_fields':
                return self._get_model_fields(**arguments)
            elif tool_name == 'generate_graph':
                return self._generate_graph(**arguments)
            elif tool_name == 'create_vendor_bill_from_pdf':
                return self._create_vendor_bill_from_pdf(**arguments)
            else:
                return {'error': f'Unknown tool: {tool_name}'}
        except Exception as e:
            _logger.exception(f"Error executing MCP tool {tool_name}")
            return {'error': str(e)}

    def _search_records(self, model: str, domain: List = None, fields: List = None, limit: int = 10) -> Dict:
        """Search for records in a model"""
        try:
            Model = self.env[model]
            domain = domain or []
            records = Model.search(domain, limit=limit)

            if fields:
                data = records.read(fields)
            else:
                data = records.read()

            return {
                'success': True,
                'count': len(data),
                'records': data
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
                'record': data
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _create_record(self, model: str, values: Dict) -> Dict:
        """Create a new record"""
        try:
            Model = self.env[model]
            record = Model.create(values)

            return {
                'success': True,
                'record_id': record.id,
                'record': record.read()[0]
            }
        except Exception as e:
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
                'record': record.read()[0]
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
        except Exception as e:
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
            result = self._process_graph_data(
                data, graph_type, x_field, y_field, group_by, aggregation, limit
            )

            # Add metadata
            result['graph_data']['title'] = title or self._generate_title(
                model, y_field, group_by, aggregation
            )
            result['graph_data']['record_count'] = len(records)

            return result

        except Exception as e:
            _logger.exception("Error generating graph")
            return {'success': False, 'error': str(e)}

    def _process_graph_data(self, data: List[Dict], graph_type: str,
                            x_field: str, y_field: str, group_by: str,
                            aggregation: str, limit: int) -> Dict:
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

        return {
            'success': True,
            'graph_data': {
                'type': graph_type,
                'labels': labels,
                'datasets': [{
                    'label': y_field.replace('_', ' ').title(),
                    'data': values
                }]
            }
        }

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
            return _mcp_server_cache[db_name]

    @api.model
    def list_tools(self):
        """List available MCP tools"""
        server = self.get_server()
        return server.list_tools()

    @api.model
    def call_tool(self, tool_name, arguments):
        """Call an MCP tool"""
        server = self.get_server()
        return server.call_tool(tool_name, arguments)
