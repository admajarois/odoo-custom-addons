{
    'name': 'POS Advance Kitchen Display',
    'version': '1.0',
    'category': 'Point of Sale',
    'summary': 'Send POS orders to Advance Kitchen Display',
    'author': 'Custom Development',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'web',
        'point_of_sale',
        'pos_restaurant',
        'bus',
    ],
    'data': [
        'data/kitchen_data.xml',
        'security/ir.model.access.csv',
        'views/kitchen_display_action.xml',
        'views/kitchen_views.xml',
        'views/kitchen_session_views.xml',
        'views/kitchen_order_views.xml',
        'views/kitchen_display_page.xml',
        'views/kitchen_loading_template.xml',   # ← add this
        'views/res_config_settings_views.xml',
        'views/kitchen_root_menu.xml',
    ],
    'assets': {
        # ── Kitchen display board ──────────────────────────────────────────
        # Only loaded when kitchen_display_page.xml calls t-call-assets.
        # kitchen_display.css owns body/html — isolated here, never global.
        'advance_kitchen.assets_kitchen_display': [
            'advance_kitchen/static/src/css/kitchen_display.css',
            'advance_kitchen/static/src/xml/kitchen_display_page_templates.xml',
            'advance_kitchen/static/src/js/kitchen_display_page.js',
        ],

        # Loading page CSS + JS are served via direct <link>/<script> tags
        # inside kitchen_loading_template.xml — they are intentionally NOT
        # in any bundle so they never load on any other page.

        # ── POS frontend ───────────────────────────────────────────────────
        'point_of_sale._assets_pos': [
            'advance_kitchen/static/src/xml/kitchen_templates.xml',
            'advance_kitchen/static/src/js/kitchen_display.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}