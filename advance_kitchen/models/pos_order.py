import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    @api.model
    def sync_from_ui(self, orders):
        paid_order_uuids = {
            order.get("uuid")
            for order in orders
            if order.get("uuid") and order.get("state") in ("paid", "done")
        }
        result = super().sync_from_ui(orders)

        result_order_ids = [
            order_data.get("id")
            for order_data in result.get("pos.order", [])
            if order_data.get("id")
        ]
        pos_orders = self.browse(result_order_ids).exists()
        if paid_order_uuids:
            pos_orders |= self.search([("uuid", "in", list(paid_order_uuids))])

        pos_orders = pos_orders.filtered(lambda order: order.state in ("paid", "done"))
        if not pos_orders:
            return result

        kitchen_order_model = self.env["pos.kitchen.order"]
        for pos_order in pos_orders:
            try:
                kitchen_order_model.auto_create_from_pos_order(pos_order)
            except Exception:
                _logger.exception("Failed to auto-create kitchen order for POS order %s", pos_order.id)

        return result
