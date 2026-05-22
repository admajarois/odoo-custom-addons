from odoo import api, fields, models


class AdvanceKitchenSession(models.Model):
    _name = "kitchen.session"
    _description = "Kitchen Display Session"
    _order = "start_at desc, id desc"

    name = fields.Char(required=True, readonly=True, copy=False, default="New")
    kitchen_id = fields.Many2one("kitchen.kitchen", required=True, index=True)
    company_id = fields.Many2one(related="kitchen_id.company_id", store=True, index=True, readonly=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True, readonly=True)
    state = fields.Selection(
        [("opened", "Opened"), ("closed", "Closed")],
        default="opened",
        required=True,
        index=True,
    )
    start_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    stop_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("kitchen.session")
        return super().create(vals_list)

    @api.model
    def get_or_create_open_session(self, kitchen_id):
        kitchen_id = int(kitchen_id)
        session = self.search([("kitchen_id", "=", kitchen_id), ("state", "=", "opened")], limit=1)
        if session:
            return session
        return self.create({
            "kitchen_id": kitchen_id,
            "user_id": self.env.user.id,
            "state": "opened",
        })

    def action_close(self):
        self.ensure_one()
        self.write({"state": "closed", "stop_at": fields.Datetime.now()})
        return True
