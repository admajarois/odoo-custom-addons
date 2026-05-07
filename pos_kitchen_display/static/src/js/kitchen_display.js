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

        const order = this.pos.selectedOrder;
        if (!order) {
            return;
        }

        const lines = order.getOrderlines ? order.getOrderlines() : [];
        if (lines.length === 0) {
            this.env.services.notification.add(_t('No items in order'), { type: 'warning' });
            return;
        }

        const orderData = {
            table_id: null,
            table_name: order.table ? order.table.name : '',
            customer_name: order.partner ? order.partner.name : '',
            note: order.note || '',
            priority: 'normal',
            lines: []
        };

        for (const line of lines) {
            let product = line.product || (line.getProduct ? line.getProduct() : null);
            if (!product) continue;

            const quantity = line.quantity || 1;
            let note = line.note || (line.getNote ? line.getNote() : '') || '';

            orderData.lines.push({
                product_id: product.id,
                product_name: product.display_name || product.name || 'Unknown',
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