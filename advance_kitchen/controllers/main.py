# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class KitchenDisplay(http.Controller):

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_kitchen_orders(self, session_id=None):
        domain = [('state', 'in', ['pending', 'in_progress', 'ready', 'done'])]
        if session_id:
            domain.append(('kitchen_session_id', '=', session_id))
        orders = request.env['pos.kitchen.order'].sudo().search_read(
            domain,
            ['id', 'name', 'table_id', 'partner_id', 'order_date', 'state', 'priority', 'note', 'line_ids'],
        )
        for order in orders:
            line_ids = order.get('line_ids') or []
            lines = request.env['pos.kitchen.order.line'].sudo().search_read(
                [('id', 'in', line_ids)],
                ['id', 'product_id', 'quantity', 'note', 'state'],
            )
            order['line_ids'] = lines
        return orders

    def _coerce_order_id(self, order_id):
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return None
        return order_id or None

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
 
    @http.route('/kitchen/start/session', type='json', auth='user', website=False)
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

    # ------------------------------------------------------------------
    # Action routes  (each one sends a bus notification after the change)
    # ------------------------------------------------------------------

    @http.route('/kitchen/order/start', type='json', auth='user', website=False)
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

    @http.route('/kitchen/order/done', type='json', auth='user', website=False)
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

    @http.route('/kitchen/order/ready', type='json', auth='user', website=False)
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

    @http.route('/kitchen/order/cancel', type='json', auth='user', website=False)
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