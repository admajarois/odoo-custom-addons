/** @odoo-module */
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

console.log("POS Kitchen Display: JS loaded");

patch(ProductScreen.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
    },

    async sendToKitchen() {
        console.log("POS Kitchen Display: sendToKitchen clicked");

        const order = this.pos.selectedOrder || (this.pos.getOrder ? this.pos.getOrder() : null);
        if (!order) {
            return;
        }

        if (!(this.pos.config && this.pos.config.module_pos_restaurant)) {
            this.env.services.notification.add(_t('Kitchen Display requires Restaurant mode enabled on this POS'), { type: 'warning' });
            return;
        }

        const lines = order.getOrderlines ? order.getOrderlines() : [];
        if (lines.length === 0) {
            this.env.services.notification.add(_t('No items in order'), { type: 'warning' });
            return;
        }

        const table = order.table_id || order.table || (order.getTable ? order.getTable() : null);
        const partner = order.partner_id || order.partner || (order.getPartner ? order.getPartner() : null);
        const tableName = table
            ? (table.table_number ? `T ${table.table_number}` : (table.display_name || table.name || ''))
            : (order.floating_order_name || '');
        const customerName = partner
            ? (partner.display_name || partner.name || '')
            : (order.floating_order_name || '');

        const orderData = {
            pos_config_id: this.pos.config && this.pos.config.id ? this.pos.config.id : null,
            table_id: null,
            table_name: tableName,
            partner_id: partner && partner.id ? partner.id : null,
            customer_name: customerName,
            note: order.note || '',
            priority: 'normal',
            creation_trigger: 'manual',
            lines: []
        };
        orderData.table_id = table && table.id ? table.id : null;

        for (const line of lines) {
            const product = line.product_id || line.product || (line.getProduct ? line.getProduct() : null);
            if (!product) continue;

            const quantity = line.qty || line.quantity || (line.getQuantity ? line.getQuantity() : 1) || 1;
            let note = line.customer_note || line.note || (line.getNote ? line.getNote() : '') || '';

            orderData.lines.push({
                product_id: product.id,
                product_name: line.full_product_name || product.display_name || product.name || 'Unknown',
                quantity: quantity,
                note: note
            });
        }

        console.log("Sending order data:", orderData);

        if (orderData.lines.length === 0) {
            this.env.services.notification.add(_t('No products found'), { type: 'warning' });
            return;
        }

        try {
            const result = await this.orm.call(
                'pos.kitchen.order',
                'send_to_kitchen',
                [orderData],
                {}
            );
            console.log("Result:", result);
            this.env.services.notification.add(_t('Order sent to kitchen!'), { type: 'success' });
        } catch (error) {
            console.error("Full error:", error);
            console.error("Error data:", error.data);
            console.error("Error message:", error.message);
            console.error("Error args:", error.args);

            let errorMsg = 'Unknown error';
            if (error.data) {
                errorMsg = error.data.message || JSON.stringify(error.data);
            } else if (error.message) {
                errorMsg = error.message;
            }

            this.env.services.notification.add(_t('Error: ') + errorMsg, { type: 'danger' });
        }
    }
});
