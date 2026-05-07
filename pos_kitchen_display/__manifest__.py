{
    'name': 'POS Kitchen Display',
    'version': '1.0',
    'category': 'Point of Sale',
    'summary': 'Send POS orders to Kitchen Display',
    'author': 'Custom Development',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'web',
        'point_of_sale',
        'pos_restaurant',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/kitchen_views.xml',
        'views/kitchen_display_page.xml',
        'views/kitchen_display_menu.xml',
        'views/kitchen_display_action.xml',
    ],
    'assets': {
        'pos_kitchen_display.assets_kitchen_display': [
            'pos_kitchen_display/static/src/css/kitchen_display.css',
            'pos_kitchen_display/static/src/xml/kitchen_display_page_templates.xml',
            'pos_kitchen_display/static/src/js/kitchen_display_page.js',
        ],
        'point_of_sale._assets_pos': [
            'pos_kitchen_display/static/src/xml/kitchen_templates.xml',
            'pos_kitchen_display/static/src/js/kitchen_display.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
