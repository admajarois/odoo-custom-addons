/** @odoo-module */

import publicWidget from '@web/legacy/js/public/public_widget';
import { renderToFragment } from "@web/core/utils/render";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.PosKitchenDisplayPage = publicWidget.Widget.extend({
    selector: "#pos_kitchen_display_root",
    events: {
        "click #refresh-btn": "_onRefresh",
        "click .kitchen-order-btn": "_onOrderAction",
        "click .kitchen-stat": "_onFilterClick",
    },

    init() {
        this._super(...arguments);
        this.pollingMs = 5000;
        this._timer = null;
        this._allOrders = [];
        this._activeFilter = null; // 'pending', 'in_progress', 'done' or null for all
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

    _onFilterClick(ev) {
        const stat = ev.currentTarget;

        const classToFilter = {
            pending: "pending",
            cooking: "in_progress",
            done: "done",
        }

        let clicked = null;
        for (const [cls, filter] of Object.entries(classToFilter)) {
            if(stat.classList.contains(cls)) {
                clicked = filter;
                break;
            }
        }
        if (this._activeFilter === clicked) {
            this._activeFilter = null;
        } else {
            this._activeFilter = clicked;
        }

        this._applyFilterAndRender();
        this._updateActiveStatUI();
    },

    _applyFilterAndRender() {
        const filtered = this._activeFilter
            ? this._allOrders.filter(o => o.state === this._activeFilter)
            : this._allOrders;
        this.renderOrders(filtered);
    },

    _updateActiveStatUI() {
        const filterToClass = {
            pending: "pending",
            in_progress: "cooking",
            done: "done",
        };

        // Remove active from all, add to the selected one
        this.el.querySelectorAll(".kitchen-stat").forEach(el => {
            el.classList.remove("active");
        });

        if (this._activeFilter) {
            const cls = filterToClass[this._activeFilter];
            this.el.querySelector(`.kitchen-stat.${cls}`)?.classList.add("active");
        }
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
            this._allOrders = this.normalizeOrders(orders);  // <-- always cache full list
            this._applyFilterAndRender();                     // <-- render respecting active filter
            this.updateStats(this._allOrders);
        } catch (err) {
            console.error("Kitchen Display: failed to load orders", err);
        }
    },

    normalizeOrders(orders) {
        return (orders || []).map(order => ({
            ...order,
            table_name: Array.isArray(order.table_id) ? order.table_id[1] : null,
            partner_name: Array.isArray(order.partner_id) ? order.partner_id[1] : null,
        }));
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
