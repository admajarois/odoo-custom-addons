/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { renderToFragment } from "@web/core/utils/render";
import { rpc } from "@web/core/network/rpc";
import { browser } from "@web/core/browser/browser";

// ── Channel / event constants ─────────────────────────────────────────────
const BUS_CHANNEL_ALL = "kitchen_display";
const BUS_EVENT_TYPE  = "kitchen_order_update";

publicWidget.registry.PosKitchenDisplayPage = publicWidget.Widget.extend({
    selector: "#pos_kitchen_display_root",
    events: {
        "click #refresh-btn":       "_onRefresh",
        "click .kitchen-order-btn": "_onOrderAction",
    },

    // ------------------------------------------------------------------
    // Life-cycle
    // ------------------------------------------------------------------

    init() {
        this._super(...arguments);
        this.pollingMs   = 5000;
        this._timer      = null;
        this._bus        = null;
        this._channels   = [];
        this._busHandler = null;
    },

    start() {
        const res = this._super(...arguments);
        this.sessionId = Number(this.el.getAttribute("data-session-id") || 0) || null;

        this.loadOrders();
        this._startBus();
        this._timer = browser.setInterval(() => this.loadOrders(), this.pollingMs);

        return res;
    },

    destroy() {
        if (this._timer) {
            browser.clearInterval(this._timer);
            this._timer = null;
        }
        this._stopBus();
        this._super(...arguments);
    },

    // ------------------------------------------------------------------
    // Bus integration
    // No top-level await / no dynamic import — those cause the
    // "await is only valid in async functions" SyntaxError when Odoo
    // bundles the file outside a true ES-module context.
    // Instead we read bus.service from this.env which publicWidget
    // populates after start() is called.
    // ------------------------------------------------------------------

    _getBusService() {
        // Odoo 17-19: services live on this.env.services
        const services = this.env && this.env.services;
        if (!services) return null;
        // Try both key variants used across Odoo versions
        return services["bus.service"] || services["bus_service"] || null;
    },

    _startBus() {
        const bus = this._getBusService();
        if (!bus) {
            console.info("Kitchen Display: bus.service unavailable – falling back to polling only.");
            return;
        }

        // Subscribe to global channel + optional session-scoped channel
        const channels = [BUS_CHANNEL_ALL];
        if (this.sessionId) {
            channels.push(`${BUS_CHANNEL_ALL}-${this.sessionId}`);
        }
        channels.forEach((ch) => bus.addChannel(ch));

        // Bind handler so we can remove the exact same reference on destroy
        this._busHandler = (notifications) => {
            for (const { type, payload } of notifications) {
                if (type === BUS_EVENT_TYPE) {
                    this._onBusNotification(payload);
                }
            }
        };
        bus.addEventListener("notification", this._busHandler);

        this._bus      = bus;
        this._channels = channels;
        console.info("Kitchen Display: bus subscribed →", channels);
    },

    _stopBus() {
        if (!this._bus) return;
        if (this._busHandler) {
            this._bus.removeEventListener("notification", this._busHandler);
            this._busHandler = null;
        }
        this._channels.forEach((ch) => this._bus.deleteChannel(ch));
        this._bus      = null;
        this._channels = [];
    },

    async _onBusNotification(payload) {
        console.debug("Kitchen Display: bus push →", payload);
        await this.loadOrders();
    },

    // ------------------------------------------------------------------
    // DOM event handlers
    // ------------------------------------------------------------------

    async _onRefresh(ev) {
        ev.preventDefault();
        await this.loadOrders();
    },

    async _onOrderAction(ev) {
        ev.preventDefault();
        const btn     = ev.currentTarget;
        const action  = btn.getAttribute("data-action");
        const orderId = btn.getAttribute("data-id");
        await this.handleAction(orderId, action);
    },

    // ------------------------------------------------------------------
    // Data layer
    // ------------------------------------------------------------------

    async loadOrders() {
        try {
            const url = this.sessionId
                ? `/kitchen/orders?session_id=${this.sessionId}`
                : "/kitchen/orders";

            const response = await fetch(url, {
                method:      "GET",
                credentials: "same-origin",
                headers:     { Accept: "application/json" },
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const orders = await response.json();
            this.renderOrders(orders);
            this.updateStats(orders);
        } catch (err) {
            console.error("Kitchen Display: failed to load orders", err);
        }
    },

    async handleAction(orderId, action) {
        if (!orderId || !action) return;
        try {
            const result = await rpc(`/kitchen/order/${action}`, {
                order_id: Number(orderId),
            });
            if (result && result.success) {
                await this.loadOrders();
            } else {
                console.error("Kitchen Display: action error", result?.error);
            }
        } catch (err) {
            console.error("Kitchen Display: action failed", err);
        }
    },

    // ------------------------------------------------------------------
    // Rendering
    // ------------------------------------------------------------------

    renderOrders(orders) {
        const container = this.el.querySelector("#orders-container");
        if (!container) return;

        const grouped = { new: [], preparing: [], ready: [], completed: [] };
        for (const order of orders || []) {
            if      (order.state === "pending")     grouped.new.push(order);
            else if (order.state === "in_progress") grouped.preparing.push(order);
            else if (order.state === "ready")       grouped.ready.push(order);
            else if (order.state === "done")        grouped.completed.push(order);
        }

        const frag = renderToFragment("advance_kitchen.KitchenBoard", {
            grouped,
            formatTime: this.formatTime.bind(this),
        });
        container.replaceChildren(frag);
    },

    updateStats(orders) {
        const pendingEl = this.el.querySelector("#stat-pending");
        const cookingEl = this.el.querySelector("#stat-cooking");
        const readyEl   = this.el.querySelector("#stat-ready");
        const doneEl    = this.el.querySelector("#stat-done");
        if (!pendingEl || !cookingEl || !readyEl || !doneEl) return;

        let pending = 0, cooking = 0, ready = 0, done = 0;
        for (const order of orders || []) {
            if      (order.state === "pending")     pending++;
            else if (order.state === "in_progress") cooking++;
            else if (order.state === "ready")       ready++;
            else if (order.state === "done")        done++;
        }
        pendingEl.textContent = String(pending);
        cookingEl.textContent = String(cooking);
        readyEl.textContent   = String(ready);
        doneEl.textContent    = String(done);
    },

    formatTime(dateStr) {
        if (!dateStr) return "";
        const date = new Date(dateStr);
        return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    },
});