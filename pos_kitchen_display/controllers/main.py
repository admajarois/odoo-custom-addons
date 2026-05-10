# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class KitchenDisplay(http.Controller):

    def _read_kitchen_orders(self):
        orders = request.env['pos.kitchen.order'].sudo().search_read(
            [('state', 'in', ['pending', 'in_progress', 'done'])],
            ['id', 'name', 'table_id', 'partner_id', 'order_date', 'state', 'priority', 'note', 'line_ids'],
        )
        for order in orders:
            line_ids = order.get('line_ids') or []
            lines = request.env['pos.kitchen.order.line'].sudo().search_read(
                [('id', 'in', line_ids)],
                ['product_name', 'quantity', 'note', 'state'],
            )
            order['line_ids'] = lines
        return orders

    @http.route('/pos/kitchen/display', type='http', auth='user', website=False)
    def kitchen_display(self, **kw):
        """Kitchen Display page (template + static assets)."""
        return request.render('pos_kitchen_display.kitchen_display_template')

    @http.route('/pos/kitchen/orders', type='http', auth='user', methods=['GET'], csrf=False, website=False)
    def get_kitchen_orders(self, **kw):
        """Get kitchen orders for the display (JSON)."""
        orders = self._read_kitchen_orders()
        return request.make_json_response(orders)

    def _coerce_order_id(self, order_id):
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return None
        return order_id or None

    @http.route('/pos/kitchen/order/start', type='jsonrpc', auth='user', website=False)
    def start_order(self, order_id=None, **kw):
        order_id = self._coerce_order_id(order_id)
        if not order_id:
            return {'success': False, 'error': 'Missing order_id'}

        order = request.env['pos.kitchen.order'].sudo().browse(order_id)
        if not order.exists():
            return {'success': False, 'error': 'Order not found'}

        order.action_start()
        return {'success': True}

    @http.route('/pos/kitchen/order/done', type='jsonrpc', auth='user', website=False)
    def mark_order_done(self, order_id=None, **kw):
        order_id = self._coerce_order_id(order_id)
        if not order_id:
            return {'success': False, 'error': 'Missing order_id'}

        order = request.env['pos.kitchen.order'].sudo().browse(order_id)
        if not order.exists():
            return {'success': False, 'error': 'Order not found'}

        order.action_done()
        return {'success': True}

    @http.route('/pos/kitchen/order/cancel', type='jsonrpc', auth='user', website=False)
    def cancel_order(self, order_id=None, **kw):
        order_id = self._coerce_order_id(order_id)
        if not order_id:
            return {'success': False, 'error': 'Missing order_id'}

        order = request.env['pos.kitchen.order'].sudo().browse(order_id)
        if not order.exists():
            return {'success': False, 'error': 'Order not found'}

        order.action_cancel()
        return {'success': True}
