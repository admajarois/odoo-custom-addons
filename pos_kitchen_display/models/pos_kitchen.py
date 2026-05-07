from odoo import models, fields, api
from odoo.exceptions import UserError
import logging
import traceback
import json

_logger = logging.getLogger(__name__)


class PosKitchenOrder(models.Model):
    _name = 'pos.kitchen.order'
    _description = 'Kitchen Order from POS'
    _order = 'create_date desc'

    name = fields.Char(string='Order Reference', required=True, copy=False, readonly=True, default='New')
    pos_order_id = fields.Many2one('pos.order', string='POS Order', readonly=True, index=True)
    table_id = fields.Integer(string='Table ID', index=True)
    table_name = fields.Char(string='Table Name')
    customer_name = fields.Char(string='Customer')
    order_date = fields.Datetime(string='Order Date', default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', string='Cashier', default=lambda self: self.env.user)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='pending', tracking=True)
    line_ids = fields.One2many('pos.kitchen.order.line', 'order_id', string='Order Lines')
    note = fields.Text(string='Notes')
    priority = fields.Selection([
        ('normal', 'Normal'),
        ('rush', 'Rush')
    ], string='Priority', default='normal')
    color = fields.Char(compute='_compute_color', string='Color')

    @api.model
    def create(self, vals_list):
        # Handle both single dict and list of dicts
        if isinstance(vals_list, list):
            vals = vals_list[0] if vals_list else {}
        else:
            vals = vals_list

        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('pos.kitchen.order') or 'New'
        return super().create(vals)

    @api.depends('state', 'priority')
    def _compute_color(self):
        for order in self:
            if order.state == 'cancelled':
                order.color = 'red'
            elif order.priority == 'rush':
                order.color = 'orange'
            elif order.state == 'in_progress':
                order.color = 'yellow'
            else:
                order.color = 'white'

    def action_start(self):
        self.write({'state': 'in_progress'})
        return True

    def action_done(self):
        self.write({'state': 'done'})
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True

    def action_reset(self):
        self.write({'state': 'pending'})
        return True

    @api.model
    def send_to_kitchen(self, order_data):
        """Create kitchen order from POS order data"""
        try:
            _logger.info('=== SEND TO KITCHEN ===')
            _logger.info('Order data type: %s', type(order_data))
            _logger.info('Order data: %s', order_data)

            # Handle case where order_data comes as a list of key-value pairs
            if isinstance(order_data, list):
                # Convert list of [key, value] pairs to dict
                order_data = dict(order_data)
                _logger.info('Converted to dict: %s', order_data)

            # Normalize any incoming POS order reference so we never save 0 into a many2one
            pos_order_id = order_data.get('pos_order_id')
            if isinstance(pos_order_id, (str, bytes)):
                pos_order_id = pos_order_id.strip()
            if not pos_order_id or str(pos_order_id) in ('0', 'False', 'false', 'None', 'none', ''):
                pos_order_id = False
            else:
                try:
                    pos_order_id = int(pos_order_id)
                except (TypeError, ValueError):
                    pos_order_id = False

            vals = {
                'name': 'New',
                'pos_order_id': pos_order_id,
                'table_id': order_data.get('table_id') or False,
                'table_name': order_data.get('table_name', ''),
                'customer_name': order_data.get('customer_name', ''),
                'order_date': fields.Datetime.now(),
                'user_id': self.env.user.id,
                'note': order_data.get('note', ''),
                'priority': order_data.get('priority', 'normal'),
            }

            _logger.info('Creating kitchen order with vals: %s', vals)
            kitchen_order = self.create(vals)
            _logger.info('Kitchen order created: %s', kitchen_order.id)

            # Create order lines
            lines = order_data.get('lines', [])
            _logger.info('Creating %s order lines', len(lines))

            if not lines:
                raise UserError('No order lines to send')

            for i, line in enumerate(lines):
                # Handle case where line is a list of key-value pairs
                if isinstance(line, list):
                    line = dict(line)

                # Validate required fields
                product_name = line.get('product_name')
                if not product_name:
                    _logger.warning('Skipping line %s: no product_name', i)
                    continue

                # Handle note - it might be a JSON string like "[]" or "null"
                note = line.get('note') or ''
                if isinstance(note, str):
                    # If note looks like a JSON array/string, try to parse it
                    if note in ('[]', 'null', 'undefined', ''):
                        note = ''
                    elif note.startswith('[') or note.startswith('{'):
                        try:
                            parsed = json.loads(note)
                            if isinstance(parsed, list):
                                note = ', '.join(str(n) for n in parsed) if parsed else ''
                            elif isinstance(parsed, dict):
                                note = str(parsed)
                        except Exception:
                            pass

                line_vals = {
                    'order_id': kitchen_order.id,
                    'product_name': product_name,
                    'product_id': line.get('product_id') or False,
                    'quantity': line.get('quantity', 1) or 1,
                    'note': note,
                    'state': 'pending',
                }
                _logger.info('Creating line %s: %s', i, line_vals)
                self.env['pos.kitchen.order.line'].create(line_vals)

            _logger.info('=== KITCHEN ORDER COMPLETED ===')
            return {'success': True, 'order_id': kitchen_order.id, 'name': kitchen_order.name}

        except Exception as e:
            _logger.error('=== ERROR IN SEND_TO_KITCHEN ===')
            _logger.error('Error: %s', str(e))
            _logger.error('Traceback: %s', traceback.format_exc())
            raise UserError(f'Failed to send to kitchen: {str(e)}')


class PosKitchenOrderLine(models.Model):
    _name = 'pos.kitchen.order.line'
    _description = 'Kitchen Order Line'
    _order = 'create_date asc'

    order_id = fields.Many2one('pos.kitchen.order', string='Order', required=True, ondelete='cascade')
    product_id = fields.Integer(string='Product ID')
    product_name = fields.Char(string='Product Name', required=True)
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    note = fields.Char(string='Special Instructions')
    state = fields.Selection([
        ('pending', 'Pending'),
        ('cooking', 'Cooking'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='pending', tracking=True)
    create_date = fields.Datetime(string='Created At', default=fields.Datetime.now)
    done_date = fields.Datetime(string='Done At')

    def action_start_cooking(self):
        self.write({'state': 'cooking'})
        return True

    def action_done(self):
        self.write({
            'state': 'done',
            'done_date': fields.Datetime.now()
        })
        if self.order_id.line_ids.filtered(lambda l: l.state not in ['done', 'cancelled']):
            return True
        self.order_id.write({'state': 'done'})
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        if self.order_id.line_ids.filtered(lambda l: l.state not in ['done', 'cancelled']):
            return True
        self.order_id.write({'state': 'cancelled'})
        return True

    def action_reset(self):
        self.write({'state': 'pending', 'done_date': False})
        return True