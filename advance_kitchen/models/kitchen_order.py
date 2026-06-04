from odoo import models, fields, api, _
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
    table_name = fields.Char(string='Table Name')
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
        lines = self.mapped('line_ids').filtered(lambda line: line.state not in ('done', 'cancelled'))
        lines.write({'state': 'cooking', 'date_done': False})
        self.write({'state': 'in_progress'})
        return True

    def action_done(self):
        lines = self.mapped('line_ids').filtered(lambda line: line.state != 'cancelled')
        lines.write({
            'state': 'done',
            'date_done': fields.Datetime.now(),
        })
        self.write({'state': 'done'})
        return True

    def action_ready(self):
        lines = self.mapped('line_ids').filtered(lambda line: line.state not in ('done', 'cancelled'))
        lines.write({'state': 'ready'})
        self.write({'state': 'ready'})
        return True

    def action_cancel(self):
        self.mapped('line_ids').filtered(lambda line: line.state != 'done').write({'state': 'cancelled'})
        self.write({'state': 'cancelled'})
        return True

    def action_reset(self):
        self.mapped('line_ids').write({'state': 'pending', 'date_done': False})
        self.write({'state': 'pending'})
        return True

    def notify_kitchen_display(self, order):
        """
        Push a real-time update to all subscribed kitchen display clients.
        """
        session = order.kitchen_session_id
        payload = {
            "order_id": order.id,
            "name": order.name,
            "state": order.state,
            "session_id": session.id if session else None,
        }

        self.env["bus.bus"]._sendone(
            "kitchen_display",
            "kitchen_order_update",
            payload,
        )

        if session:
            self.env["bus.bus"]._sendone(
                f"kitchen_display-{session.id}",
                "kitchen_order_update",
                payload,
            )

    def _get_pos_order_table_name(self, pos_order):
        table = getattr(pos_order, "table_id", False)
        if table:
            table_number = table.table_number
            if table_number:
                return f"T {table_number}"
            return table.display_name or ""
        return pos_order.floating_order_name or ""

    def _get_pos_order_customer_name(self, pos_order):
        partner = pos_order.partner_id
        if partner:
            return partner.display_name or partner.name or ""
        return pos_order.floating_order_name or ""

    def _prepare_order_data_from_pos_order(self, pos_order, kitchen):
        lines = []
        for order_line in pos_order.lines:
            if order_line.qty <= 0 or not order_line.product_id:
                continue
            lines.append({
                "product_id": order_line.product_id.id,
                "product_name": order_line.full_product_name or order_line.product_id.display_name,
                "quantity": order_line.qty,
                "note": order_line.customer_note or order_line.note or "",
            })

        table = getattr(pos_order, "table_id", False)
        note = "\n".join(filter(None, [pos_order.general_customer_note, pos_order.internal_note]))
        return {
            "creation_trigger": "automatic",
            "pos_order_id": pos_order.id,
            "pos_config_id": pos_order.config_id.id,
            "kitchen_id": kitchen.id,
            "table_id": table.id if table else False,
            "table_name": self._get_pos_order_table_name(pos_order),
            "partner_id": pos_order.partner_id.id or False,
            "customer_name": self._get_pos_order_customer_name(pos_order),
            "note": note,
            "priority": "normal",
            "lines": lines,
        }

    @api.model
    def auto_create_from_pos_order(self, pos_order):
        pos_order = pos_order.exists()
        if not pos_order or pos_order.state not in ("paid", "done"):
            return {"success": False, "skipped": True, "reason": "POS order is not paid"}

        kitchen = pos_order.config_id.kitchen_id
        if not kitchen:
            return {"success": False, "skipped": True, "reason": "No kitchen configured"}
        if kitchen.order_creation_mode != "automatic":
            return {"success": False, "skipped": True, "reason": "Kitchen is manual"}

        existing = self.search([
            ("pos_order_id", "=", pos_order.id),
            ("state", "!=", "cancelled"),
        ], limit=1)
        if existing:
            return {"success": True, "skipped": True, "order_id": existing.id, "name": existing.name}

        order_data = self._prepare_order_data_from_pos_order(pos_order, kitchen)
        if not order_data["lines"]:
            return {"success": False, "skipped": True, "reason": "No kitchen lines"}
        return self.send_to_kitchen(order_data)

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

            if pos_order_id:
                existing = self.search([
                    ('pos_order_id', '=', pos_order_id),
                    ('state', '!=', 'cancelled'),
                ], limit=1)
                if existing:
                    _logger.info('Kitchen order already exists for POS order %s: %s', pos_order_id, existing.id)
                    return {
                        'success': True,
                        'order_id': existing.id,
                        'name': existing.name,
                        'existing': True,
                    }

            vals = {
                'name': 'New',
                'pos_order_id': pos_order_id,
                'table_id': order_data.get('table_id') or False,
                'table_name': order_data.get('table_name') or '',
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

            kitchen = self.env["kitchen.kitchen"].sudo().browse(int(kitchen_id)).exists()
            if not kitchen:
                raise UserError(_("Kitchen not found."))

            creation_trigger = order_data.get("creation_trigger") or "manual"
            if kitchen.order_creation_mode == "automatic" and creation_trigger != "automatic":
                raise UserError(_("This kitchen creates orders automatically after POS payment."))

            vals["kitchen_id"] = kitchen.id
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
            self.notify_kitchen_display(kitchen_order)
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
