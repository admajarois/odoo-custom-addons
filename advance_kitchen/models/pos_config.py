from odoo import _, api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    kitchen_id = fields.Many2one("kitchen.kitchen", string="Kitchen", help="Default kitchen destination for orders sent from this POS.")
    kitchen_order_creation_mode = fields.Selection(
        related="kitchen_id.order_creation_mode",
        readonly=True,
        string="Kitchen Order Creation",
    )

    @api.model
    def load_onboarding_restaurant_scenario(self, with_demo_data=True):
        result = super().load_onboarding_restaurant_scenario(with_demo_data=with_demo_data)
        config_id = result.get("config_id")
        if not config_id:
            return result

        config = self.env["pos.config"].browse(config_id).exists()
        if not config:
            return result

        if config.kitchen_id:
            return result

        kitchen = self.env["kitchen.kitchen"].search([("company_id", "=", config.company_id.id)], limit=1)
        if not kitchen:
            kitchen = self.env["kitchen.kitchen"].create(
                {
                    "name": _("Kitchen"),
                    "company_id": config.company_id.id,
                    "active": True,
                }
            )
        config.kitchen_id = kitchen.id
        return result
