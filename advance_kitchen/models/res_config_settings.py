from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_kitchen_id = fields.Many2one('kitchen.kitchen', related='pos_config_id.kitchen_id', readonly=False, string='Kitchen')