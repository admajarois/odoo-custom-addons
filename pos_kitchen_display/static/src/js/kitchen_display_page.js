/** @odoo-module */

import publicWidget from '@web/legacy/js/public/public_widget';
import { renderToFragment } from "@web/core/utils/render";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.PosKitchenDisplayPage = publicWidget.Widget.extend({
    selector: "#pos_kitchen_display_root",
    events: {
        "click #refresh-btn": "_onRefresh",
        "click .kitchen-order-btn": "_onOrderAction",
    },

    init() {
        this._super(...arguments);
        this.pollingMs = 5000;
        this._timer = null;
    },

    start() {
        const res = this._super(...arguments);
        this.loadOrders();
        this._timer = window.setInterval(() => this.loadOrders(), this.pollingMs);
        return res;
    },

    destroy() {
        if (this._timer) {
            window.clearInterval(this._timer);
            this._timer = null;
        }
        this._super(...arguments);
    },

    async _onRefresh(ev) {
        ev.preventDefault();
        await this.loadOrders();
    },

    async _onOrderAction(ev) {
        ev.preventDefault();
        const btn = ev.currentTarget;
        const action = btn.getAttribute("data-action");
        const orderId = btn.getAttribute("data-id");
        await this.handleAction(orderId, action);
    },

    async loadOrders() {
        try {
            const response = await fetch("/pos/kitchen/orders", {
                method: "GET",
                credentials: "same-origin",
                headers: { Accept: "application/json" },
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const orders = await response.json();
            this.renderOrders(orders);
            this.updateStats(orders);
        } catch (err) {
            console.error("Kitchen Display: failed to load orders", err);
        }
    },

    renderOrders(orders) {
        const container = this.el.querySelector("#orders-container");
        if (!container) return;

        const frag = renderToFragment("pos_kitchen_display.KitchenOrdersContainer", {
            orders: orders || [],
            formatTime: this.formatTime.bind(this),
        });
        container.replaceChildren(frag);
    },

    updateStats(orders) {
        const pendingEl = this.el.querySelector("#stat-pending");
        const cookingEl = this.el.querySelector("#stat-cooking");
        const doneEl = this.el.querySelector("#stat-done");
        if (!pendingEl || !cookingEl || !doneEl) return;

        let pending = 0;
        let cooking = 0;
        let done = 0;
        for (const order of orders || []) {
            if (order.state === "pending") pending++;
            else if (order.state === "in_progress") cooking++;
            else if (order.state === "done") done++;
        }
        pendingEl.textContent = String(pending);
        cookingEl.textContent = String(cooking);
        doneEl.textContent = String(done);
    },

    formatTime(dateStr) {
        if (!dateStr) return "";
        const date = new Date(dateStr);
        return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    },

    async handleAction(orderId, action) {
        if (!orderId || !action) return;
        try {
            const result = await rpc(`/pos/kitchen/order/${action}`, { order_id: Number(orderId) });
            if (result && result.success) {
                await this.loadOrders();
            } else {
                console.error("Kitchen Display: action error", result && result.error);
            }
        } catch (err) {
            console.error("Kitchen Display: action failed", err);
        }
    },
});
