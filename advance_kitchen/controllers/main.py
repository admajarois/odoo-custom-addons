# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class KitchenDisplay(http.Controller):

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _column_exists(self, table_name, column_name):
        request.env.cr.execute(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_name = %s
               AND column_name = %s
             LIMIT 1
            """,
            (table_name, column_name),
        )
        return bool(request.env.cr.fetchone())

    def _read_kitchen_orders(self, session_id=None):
        domain = [('state', 'in', ['pending', 'in_progress', 'ready', 'done'])]
        if session_id:
            domain.append(('kitchen_session_id', '=', session_id))
        order_fields = ['id', 'name', 'table_id', 'partner_id', 'order_date', 'state', 'priority', 'note', 'line_ids']
        if self._column_exists('pos_kitchen_order', 'table_name'):
            order_fields.append('table_name')
        if self._column_exists('pos_kitchen_order', 'customer_name'):
            order_fields.append('customer_name')
        orders = request.env['pos.kitchen.order'].sudo().search_read(domain, order_fields)
        for order in orders:
            table_field = order.get('table_id')
            partner_field = order.get('partner_id')
            order['table_name'] = (
                table_field[1] if isinstance(table_field, list) and len(table_field) > 1
                else order.get('table_name') or ''
            )
            order['customer_name'] = (
                partner_field[1] if isinstance(partner_field, list) and len(partner_field) > 1
                else order.get('customer_name') or ''
            )

            line_ids = order.get('line_ids') or []
            line_fields = ['id', 'product_id', 'quantity', 'note', 'state']
            if self._column_exists('pos_kitchen_order_line', 'product_name'):
                line_fields.append('product_name')
            lines = request.env['pos.kitchen.order.line'].sudo().search_read(
                [('id', 'in', line_ids)],
                line_fields,
            )
            line_map = {line['id']: line for line in lines}
            normalized_lines = []
            for line_id in line_ids:
                line = line_map.get(line_id)
                if not line:
                    continue
                product_field = line.get('product_id')
                line['product_name'] = (
                    product_field[1] if isinstance(product_field, list) and len(product_field) > 1
                    else line.get('product_name') or ''
                )
                normalized_lines.append(line)
            order['line_ids'] = normalized_lines
        return orders

    def _coerce_order_id(self, order_id):
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return None
        return order_id or None

    def _coerce_line_id(self, line_id):
        try:
            line_id = int(line_id)
        except (TypeError, ValueError):
            return None
        return line_id or None

    def _read_completed_items(self, session_id=None, search=""):
        orders = self._read_kitchen_orders(session_id=session_id)
        term = (search or "").strip().lower()
        rows = []
        for order in orders:
            for line in (order.get("line_ids") or []):
                if line.get("state") != "done":
                    continue
                row = {
                    "order_name": order.get("name") or "",
                    "product_name": line.get("product_name") or "",
                    "table_name": order.get("table_name") or "",
                    "customer_name": order.get("customer_name") or "",
                    "quantity": line.get("quantity") or 0,
                    "order_date": order.get("order_date") or "",
                }
                if term:
                    haystack = " ".join([
                        row["order_name"],
                        row["product_name"],
                        row["table_name"],
                        row["customer_name"],
                    ]).lower()
                    if term not in haystack:
                        continue
                rows.append(row)
        rows.sort(key=lambda r: r.get("order_date") or "", reverse=True)
        return rows

    def _notify_kitchen_bus(self, order):
        """
        Push a real-time update to all subscribed kitchen display clients.

        Two channels are used:
          - "kitchen_display"                  → every open kitchen screen
          - "kitchen_display-<session_id>"     → only the screen tied to this session

        The frontend listens for event type  "kitchen_order_update".
        """
        session_id = None
        # pos.kitchen.order may link to a kitchen.session via kitchen_session_id
        if order.kitchen_session_id:
            session_id = order.kitchen_session_id.id

        payload = {
            "order_id":   order.id,
            "name":       order.name,
            "state":      order.state,
            "session_id": session_id,
        }

        # Broadcast to all kitchen displays
        request.env["bus.bus"]._sendone(
            "kitchen_display",
            "kitchen_order_update",
            payload,
        )

        # Also broadcast to the session-specific channel
        if session_id:
            request.env["bus.bus"]._sendone(
                f"kitchen_display-{session_id}",
                "kitchen_order_update",
                payload,
            )

        _logger.debug("Kitchen Display: bus notification sent for order %s → state=%s", order.id, order.state)

    # ------------------------------------------------------------------
    # Page routes
    # ------------------------------------------------------------------

    @http.route('/kitchen', type='http', auth='user', website=False)
    def kitchen_session_select(self, **kw):
        """Kitchen session selector (like POS config selection)."""
        kitchens = request.env["kitchen.kitchen"].sudo().search(
            [("active", "=", True)],
            order="name asc",
        )
        return request.render(
            "advance_kitchen.kitchen_session_select_template",
            {"kitchens": kitchens},
        )

    @http.route('/kitchen/start', type='http', auth='user', website=False)
    def kitchen_session_start(self, kitchen_id=None, **kw):
        """
        Render a loading splash page.
        The page's JS calls /kitchen/start/session (JSON) to do the real
        work, then redirects to /kitchen/display once the session is ready.
        """
        try:
            kitchen_id = int(kitchen_id)
        except (TypeError, ValueError):
            kitchen_id = None
        if not kitchen_id:
            return request.redirect("/kitchen")
 
        kitchen = request.env["kitchen.kitchen"].sudo().browse(kitchen_id)
        if not kitchen.exists():
            return request.redirect("/kitchen")
 
        return request.render(
            "advance_kitchen.kitchen_loading_template",
            {"kitchen": kitchen},
        )
 
    @http.route('/kitchen/start/session', type='jsonrpc', auth='user', website=False)
    def kitchen_session_open(self, kitchen_id=None, **kw):
        """
        JSON endpoint called by the loading page.
        Does the heavy lifting and returns the session URL.
        """
        try:
            kitchen_id = int(kitchen_id)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'Invalid kitchen_id'}
 
        if not kitchen_id:
            return {'success': False, 'error': 'Missing kitchen_id'}
 
        kitchen = request.env["kitchen.kitchen"].sudo().browse(kitchen_id)
        if not kitchen.exists():
            return {'success': False, 'error': 'Kitchen not found'}
 
        try:
            session = request.env["kitchen.session"].sudo().get_or_create_open_session(kitchen_id)
            return {
                'success': True,
                'redirect': f'/kitchen/display?session_id={session.id}',
            }
        except Exception as e:
            _logger.exception("Kitchen Display: failed to open session for kitchen %s", kitchen_id)
            return {'success': False, 'error': str(e)}


    @http.route('/kitchen/display', type='http', auth='user', website=False)
    def kitchen_display(self, **kw):
        """Kitchen Display page (template + static assets)."""
        session_id = kw.get("session_id")
        try:
            session_id = int(session_id) if session_id else None
        except (TypeError, ValueError):
            session_id = None
        if not session_id:
            return request.redirect("/kitchen")

        session = request.env["kitchen.session"].sudo().browse(session_id)
        if not session.exists() or session.state != "opened":
            return request.redirect("/kitchen")

        return request.render(
            "advance_kitchen.kitchen_display_template",
            {"kitchen_session": session},
        )

    @http.route('/kitchen/completed', type='http', auth='user', website=False)
    def kitchen_completed(self, **kw):
        session_id = kw.get("session_id")
        search = kw.get("q", "")
        try:
            session_id = int(session_id) if session_id else None
        except (TypeError, ValueError):
            session_id = None
        if not session_id:
            return request.redirect("/kitchen")

        session = request.env["kitchen.session"].sudo().browse(session_id)
        if not session.exists() or session.state != "opened":
            return request.redirect("/kitchen")

        completed_items = self._read_completed_items(session_id=session_id, search=search)
        return request.render(
            "advance_kitchen.kitchen_completed_template",
            {
                "kitchen_session": session,
                "completed_items": completed_items,
                "search_query": search or "",
            },
        )

    @http.route('/kitchen/orders', type='http', auth='user', methods=['GET'], csrf=False, website=False)
    def get_kitchen_orders(self, **kw):
        """Get kitchen orders for the display (JSON)."""
        session_id = kw.get("session_id")
        try:
            session_id = int(session_id) if session_id else None
        except (TypeError, ValueError):
            session_id = None
        orders = self._read_kitchen_orders(session_id=session_id)
        return request.make_json_response(orders)

    @http.route('/kitchen/completed/items', type='http', auth='user', methods=['GET'], csrf=False, website=False)
    def get_kitchen_completed_items(self, **kw):
        session_id = kw.get("session_id")
        search = kw.get("q", "")
        try:
            session_id = int(session_id) if session_id else None
        except (TypeError, ValueError):
            session_id = None
        if not session_id:
            return request.make_json_response([])
        rows = self._read_completed_items(session_id=session_id, search=search)
        return request.make_json_response(rows)

    # ------------------------------------------------------------------
    # Action routes  (each one sends a bus notification after the change)
    # ------------------------------------------------------------------

    @http.route('/kitchen/order/start', type='jsonrpc', auth='user', website=False)
    def start_order(self, order_id=None, **kw):
        order_id = self._coerce_order_id(order_id)
        if not order_id:
            return {'success': False, 'error': 'Missing order_id'}

        order = request.env['pos.kitchen.order'].sudo().browse(order_id)
        if not order.exists():
            return {'success': False, 'error': 'Order not found'}

        order.action_start()
        self._notify_kitchen_bus(order)
        return {'success': True}

    @http.route('/kitchen/order/done', type='jsonrpc', auth='user', website=False)
    def mark_order_done(self, order_id=None, **kw):
        order_id = self._coerce_order_id(order_id)
        if not order_id:
            return {'success': False, 'error': 'Missing order_id'}

        order = request.env['pos.kitchen.order'].sudo().browse(order_id)
        if not order.exists():
            return {'success': False, 'error': 'Order not found'}

        order.action_done()
        self._notify_kitchen_bus(order)
        return {'success': True}

    @http.route('/kitchen/order/ready', type='jsonrpc', auth='user', website=False)
    def mark_order_ready(self, order_id=None, **kw):
        order_id = self._coerce_order_id(order_id)
        if not order_id:
            return {'success': False, 'error': 'Missing order_id'}

        order = request.env['pos.kitchen.order'].sudo().browse(order_id)
        if not order.exists():
            return {'success': False, 'error': 'Order not found'}

        order.action_ready()
        self._notify_kitchen_bus(order)
        return {'success': True}

    @http.route('/kitchen/order/cancel', type='jsonrpc', auth='user', website=False)
    def cancel_order(self, order_id=None, **kw):
        order_id = self._coerce_order_id(order_id)
        if not order_id:
            return {'success': False, 'error': 'Missing order_id'}

        order = request.env['pos.kitchen.order'].sudo().browse(order_id)
        if not order.exists():
            return {'success': False, 'error': 'Order not found'}

        order.action_cancel()
        self._notify_kitchen_bus(order)
        return {'success': True}

    @http.route('/kitchen/line/start', type='jsonrpc', auth='user', website=False)
    def start_line(self, line_id=None, **kw):
        line_id = self._coerce_line_id(line_id)
        if not line_id:
            return {'success': False, 'error': 'Missing line_id'}

        line = request.env['pos.kitchen.order.line'].sudo().browse(line_id)
        if not line.exists():
            return {'success': False, 'error': 'Line not found'}

        line.action_start_cooking()
        self._notify_kitchen_bus(line.order_id)
        return {'success': True}

    @http.route('/kitchen/line/done', type='jsonrpc', auth='user', website=False)
    def done_line(self, line_id=None, **kw):
        line_id = self._coerce_line_id(line_id)
        if not line_id:
            return {'success': False, 'error': 'Missing line_id'}

        line = request.env['pos.kitchen.order.line'].sudo().browse(line_id)
        if not line.exists():
            return {'success': False, 'error': 'Line not found'}

        line.action_done()
        self._notify_kitchen_bus(line.order_id)
        return {'success': True}

    @http.route('/kitchen/line/ready', type='jsonrpc', auth='user', website=False)
    def ready_line(self, line_id=None, **kw):
        line_id = self._coerce_line_id(line_id)
        if not line_id:
            return {'success': False, 'error': 'Missing line_id'}

        line = request.env['pos.kitchen.order.line'].sudo().browse(line_id)
        if not line.exists():
            return {'success': False, 'error': 'Line not found'}

        line.action_ready()
        self._notify_kitchen_bus(line.order_id)
        return {'success': True}

    @http.route('/kitchen/line/cancel', type='jsonrpc', auth='user', website=False)
    def cancel_line(self, line_id=None, **kw):
        line_id = self._coerce_line_id(line_id)
        if not line_id:
            return {'success': False, 'error': 'Missing line_id'}

        line = request.env['pos.kitchen.order.line'].sudo().browse(line_id)
        if not line.exists():
            return {'success': False, 'error': 'Line not found'}

        line.action_cancel()
        self._notify_kitchen_bus(line.order_id)
        return {'success': True}

    @http.route('/kitchen/line/reset', type='jsonrpc', auth='user', website=False)
    def reset_line(self, line_id=None, **kw):
        line_id = self._coerce_line_id(line_id)
        if not line_id:
            return {'success': False, 'error': 'Missing line_id'}

        line = request.env['pos.kitchen.order.line'].sudo().browse(line_id)
        if not line.exists():
            return {'success': False, 'error': 'Line not found'}

        line.action_reset()
        if line.order_id.state in ('done', 'cancelled'):
            line.order_id.write({'state': 'pending'})
        self._notify_kitchen_bus(line.order_id)
        return {'success': True}

    @http.route('/kitchen/session/close', type='jsonrpc', auth='user', website=False)
    def close_session(self, session_id=None, **kw):
        try:
            session_id = int(session_id)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'Invalid session_id'}

        session = request.env['kitchen.session'].sudo().browse(session_id)
        if not session.exists():
            return {'success': False, 'error': 'Session not found'}
        if session.state != 'opened':
            return {'success': False, 'error': 'Session already closed'}

        session.action_close()
        return {'success': True, 'redirect': '/kitchen'}

    # ------------------------------------------------------------------
    # Backward-compatible routes (old URLs)
    # ------------------------------------------------------------------

    @http.route('/pos/kitchen', type='http', auth='user', website=False)
    def legacy_kitchen_session_select(self, **kw):
        return request.redirect("/kitchen")

    @http.route('/pos/kitchen/start', type='http', auth='user', website=False)
    def legacy_kitchen_session_start(self, **kw):
        return request.redirect("/kitchen")

    @http.route('/pos/kitchen/display', type='http', auth='user', website=False)
    def legacy_kitchen_display(self, **kw):
        session_id = kw.get("session_id")
        return request.redirect(f"/kitchen/display?session_id={session_id}" if session_id else "/kitchen")

    @http.route('/pos/kitchen/orders', type='http', auth='user', website=False)
    def legacy_kitchen_orders(self, **kw):
        session_id = kw.get("session_id")
        return request.redirect(f"/kitchen/orders?session_id={session_id}" if session_id else "/kitchen/orders")
