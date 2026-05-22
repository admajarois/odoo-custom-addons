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
    kitchen_id = fields.Many2one('kitchen.kitchen', string='Kitchen', readonly=True, index=True)
    kitchen_session_id = fields.Many2one('kitchen.session', string='Kitchen Session', readonly=True, index=True)
    table_id = fields.Many2one('restaurant.table', string='Table')
    partner_id = fields.Many2one('res.partner', string='Customer')
    customer_name = fields.Char(string='Customer Name')
    order_date = fields.Datetime(string='Order Date', default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', string='Cashier', default=lambda self: self.env.user)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('ready', 'Ready'),
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

    def action_ready(self):
        self.write({'state': 'ready'})
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
                'partner_id': order_data.get('partner_id') or False,
                'customer_name': order_data.get('customer_name') or order_data.get('partner_name') or '',
                'order_date': fields.Datetime.now(),
                'user_id': self.env.user.id,
                'note': order_data.get('note', ''),
                'priority': order_data.get('priority', 'normal'),
            }

            # Attach to an open kitchen session (per POS config) if possible.
            pos_config_id = order_data.get("pos_config_id")
            kitchen_id = order_data.get("kitchen_id")
            if pos_config_id and not kitchen_id:
                config = self.env["pos.config"].sudo().browse(int(pos_config_id))
                kitchen_id = config.kitchen_id.id if config.exists() else False

            if not kitchen_id:
                raise UserError("No Kitchen configured for this POS. Set it on Point of Sale > Configuration > Point of Sale.")

            vals["kitchen_id"] = int(kitchen_id)
            kitchen_session = self.env["kitchen.session"].sudo().get_or_create_open_session(vals["kitchen_id"])
            vals["kitchen_session_id"] = kitchen_session.id

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
                    'product_id': line.get('product_id') or False,
                    'product_name': product_name,
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

    
    def notify_kitchen_display(self, order):
        """
        Push a real-time update to all subscribed kitchen display clients.
    
        Channels
        --------
        - "kitchen_display"                        → all displays
        - "kitchen_display-<session_id>"           → session-specific display
    
        The frontend listens for the event type "kitchen_order_update".
        """
        payload = {
            "order_id":   order.id,
            "state":      order.state,
            "session_id": order.session_id.id if order.session_id else None,
        }
    
        # Broadcast to the global kitchen channel (all displays)
        self.env["bus.bus"]._sendone(
            "kitchen_display",
            "kitchen_order_update",
            payload,
        )
    
        # Also broadcast to the session-specific channel if applicable
        if order.session_id:
            self.env["bus.bus"]._sendone(
                f"kitchen_display-{order.session_id.id}",
                "kitchen_order_update",
                payload,
            )
    



class PosKitchenOrderLine(models.Model):
    _name = 'pos.kitchen.order.line'
    _description = 'Kitchen Order Line'
    _order = 'create_date asc'

    order_id = fields.Many2one('pos.kitchen.order', string='Order', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product')
    product_name = fields.Char(string='Product Name', required=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', related='product_id.uom_id', readonly=True)
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    date_done = fields.Datetime(string='Done Date')
    note = fields.Char(string='Special Instructions')
    state = fields.Selection([
        ('pending', 'Pending'),
        ('cooking', 'Cooking'),
        ('ready', 'Ready'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='pending', tracking=True)

    def _sync_parent_order_state(self):
        for order in self.mapped('order_id'):
            states = set(order.line_ids.mapped('state'))
            if not states:
                continue
            if states.issubset({'done', 'cancelled'}):
                order.write({'state': 'done'})
            elif 'cooking' in states:
                order.write({'state': 'in_progress'})
            elif 'ready' in states:
                order.write({'state': 'ready'})
            else:
                order.write({'state': 'pending'})

    def action_start_cooking(self):
        self.write({'state': 'cooking'})
        self._sync_parent_order_state()
        return True

    def action_done(self):
        self.write({
            'state': 'done',
            'date_done': fields.Datetime.now(),
        })
        self._sync_parent_order_state()
        return True

    def action_ready(self):
        self.write({'state': 'ready'})
        self._sync_parent_order_state()
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        self._sync_parent_order_state()
        return True

    def action_reset(self):
        self.write({'state': 'pending', 'date_done': False})
        self._sync_parent_order_state()
        return True
