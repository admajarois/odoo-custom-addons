from odoo import fields, models, api


class KitchenKitchen(models.Model):
    _name = "kitchen.kitchen"
    _description = "Kitchen"
    _order = "name asc, id asc"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True, index=True)
    active = fields.Boolean(default=True)
    session_ids = fields.One2many("kitchen.session", "kitchen_id", string="Sessions")
    order_ids = fields.One2many("pos.kitchen.order", "kitchen_id", string="Kitchen Orders")
    current_session_id = fields.Many2one("kitchen.session", string="Current Session", compute="_compute_current_session_id")
    current_user_id = fields.Many2one("res.users", string="Current User", compute="_compute_current_session_id")


    @api.depends("session_ids")
    def _compute_current_session_id(self):
        for kitchen in self:
            open_session = kitchen.session_ids.filtered(lambda s: s.state == "opened")
            kitchen.current_session_id = open_session and open_session[0] or False
            kitchen.current_user_id = kitchen.current_session_id.user_id if kitchen.current_session_id else False


    def open_kitchen_session(self):
        self.ensure_one()
        return self.action_open_display()

    def action_view_kitchen_orders(self):
        self.ensure_one()
        return {
            "name": "Kitchen Orders",
            "type": "ir.actions.act_window",
            "res_model": "pos.kitchen.order",
            "view_mode": "tree,form",
            "domain": [("kitchen_id", "=", self.id)],
        }
    
    def action_open_display(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/kitchen/start?kitchen_id={self.id}",
            "target": "self",
        }
