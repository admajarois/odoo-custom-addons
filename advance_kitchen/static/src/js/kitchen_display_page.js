/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { renderToFragment } from "@web/core/utils/render";
import { rpc } from "@web/core/network/rpc";
import { browser } from "@web/core/browser/browser";

const BUS_CHANNEL_ALL = "kitchen_display";
const BUS_EVENT_TYPE = "kitchen_order_update";
const COMPLETED_PREVIEW_LIMIT = 8;

publicWidget.registry.PosKitchenDisplayPage = publicWidget.Widget.extend({
    selector: "#akd-root",
    events: {
        "click [data-action]": "_onOrderAction",
        "click .akd-nav-item[data-filter-state]": "_onStateFilterClick",
        "click .akd-nav-item[data-filter-station]": "_onStationFilterClick",
        "click .akd-tab[data-tab-state]": "_onTabClick",
        "input #akd-search-inline": "_onSearchInlineInput",
        "click #akd-search-clear": "_onSearchInlineClear",
        "click #btn-sidebar-toggle": "_onSidebarToggle",
        "click #btn-sound": "_onToggleSound",
        "click .akd-view-all-btn": "_onViewAll",
        "click #btn-hold": "_onHold",
        "click #btn-recall": "_onRecall",
        "click #btn-more": "_onMore",
        "click #akd-modal-backdrop": "_onBackdropClick",
        "click [data-modal-close]": "_onModalClose",
        "click #akd-search-apply": "_onSearchApply",
        "click #akd-open-settings": "_onOpenSettings",
        "click #akd-close-session": "_onCloseSession",
        "change #akd-darkmode-toggle": "_onThemeToggle",
    },

    init() {
        this._super(...arguments);
        this.pollingMs = 5000;
        this._timer = null;
        this._clockTimer = null;
        this._bus = null;
        this._channels = [];
        this._busHandler = null;

        this.activeStateFilter = "all";
        this.activeStationFilter = "all";
        this.searchTerm = "";
        this.paused = false;
        this.soundEnabled = browser.localStorage.getItem("akd_sound_enabled") !== "0";

        this._allOrders = [];
        this._knownPendingLineIds = new Set();
        this._lastRenderSignature = "";
        this.sessionStart = null;
        this.lastSyncAt = null;
    },

    start() {
        const res = this._super(...arguments);
        this.sessionId = Number(this.el.getAttribute("data-session-id") || 0) || null;
        const sessionMeta = window.__KDS_SESSION__ || {};
        this.sessionStart = sessionMeta.start_at ? new Date(sessionMeta.start_at) : null;
        this.theme = browser.localStorage.getItem("akd_theme") || "dark";

        this._applySoundState();
        this._applyTheme();
        this._updateFilterUI();
        this._updateSyncStatus();
        this._updateHoldRecallUI();

        this.loadOrders();
        this._startBus();
        this._timer = browser.setInterval(() => {
            if (!this.paused) this.loadOrders();
        }, this.pollingMs);
        this._clockTimer = browser.setInterval(() => this._updateSyncStatus(), 1000);
        this._outsideClickHandler = (ev) => this._onDocumentClick(ev);
        document.addEventListener("click", this._outsideClickHandler, true);
        this._globalClickHandler = (ev) => this._onGlobalClick(ev);
        document.addEventListener("click", this._globalClickHandler, true);
        this._globalKeyHandler = (ev) => this._onGlobalKeydown(ev);
        document.addEventListener("keydown", this._globalKeyHandler, true);
        this._resizeHandler = () => {
            this._updateFilterUI();
            this.renderItems();
        };
        window.addEventListener("resize", this._resizeHandler);

        return res;
    },

    destroy() {
        if (this._timer) browser.clearInterval(this._timer);
        if (this._clockTimer) browser.clearInterval(this._clockTimer);
        this._timer = null;
        this._clockTimer = null;
        if (this._outsideClickHandler) {
            document.removeEventListener("click", this._outsideClickHandler, true);
            this._outsideClickHandler = null;
        }
        if (this._globalClickHandler) {
            document.removeEventListener("click", this._globalClickHandler, true);
            this._globalClickHandler = null;
        }
        if (this._globalKeyHandler) {
            document.removeEventListener("keydown", this._globalKeyHandler, true);
            this._globalKeyHandler = null;
        }
        if (this._resizeHandler) {
            window.removeEventListener("resize", this._resizeHandler);
            this._resizeHandler = null;
        }
        this._stopBus();
        this._super(...arguments);
    },

    _getBusService() {
        const services = this.env && this.env.services;
        if (!services) return null;
        return services["bus.service"] || services["bus_service"] || null;
    },

    _startBus() {
        const bus = this._getBusService();
        if (!bus) return;

        const channels = [BUS_CHANNEL_ALL];
        if (this.sessionId) channels.push(`${BUS_CHANNEL_ALL}-${this.sessionId}`);
        channels.forEach((ch) => bus.addChannel(ch));

        this._busHandler = (notifications) => {
            for (const { type } of notifications) {
                if (type === BUS_EVENT_TYPE) this._onBusNotification();
            }
        };
        bus.addEventListener("notification", this._busHandler);

        this._bus = bus;
        this._channels = channels;
    },

    _stopBus() {
        if (!this._bus) return;
        if (this._busHandler) this._bus.removeEventListener("notification", this._busHandler);
        this._channels.forEach((ch) => this._bus.deleteChannel(ch));
        this._bus = null;
        this._channels = [];
        this._busHandler = null;
    },

    async _onBusNotification() {
        if (!this.paused) await this.loadOrders();
    },

    async _onOrderAction(ev) {
        ev.preventDefault();
        const btn = ev.currentTarget;
        const action = btn.getAttribute("data-action");
        const entity = btn.getAttribute("data-entity") || "order";
        const id = btn.getAttribute("data-id");
        if (!action || !id) return;

        if (entity === "line") {
            await this.handleLineAction(id, action);
            return;
        }
        await this.handleAction(id, action);
    },

    _onStateFilterClick(ev) {
        this.activeStateFilter = ev.currentTarget.getAttribute("data-filter-state") || "all";
        this._updateFilterUI();
        this.renderItems();
        this._closeSidebarOnMobile();
    },

    _onStationFilterClick(ev) {
        this.activeStationFilter = ev.currentTarget.getAttribute("data-filter-station") || "all";
        this._updateFilterUI();
        this.renderItems();
        this._closeSidebarOnMobile();
    },

    _onTabClick(ev) {
        this.activeStateFilter = ev.currentTarget.getAttribute("data-tab-state") || "all";
        this._updateFilterUI();
        this.renderItems();
    },

    _onSearchInlineInput(ev) {
        const value = ev.currentTarget.value || "";
        this.searchTerm = value.trim().toLowerCase();
        this.renderItems();
    },

    _onSearchInlineClear(ev) {
        ev.preventDefault();
        this.searchTerm = "";
        const input = this.el.querySelector("#akd-search-inline");
        if (input) input.value = "";
        this.renderItems();
    },

    _onSidebarToggle(ev) {
        ev.preventDefault();
        this.el.classList.toggle("akd-sidebar-open");
    },

    _closeSidebarOnMobile() {
        if (window.matchMedia("(max-width: 1024px)").matches) {
            this.el.classList.remove("akd-sidebar-open");
        }
    },

    _onToggleSound(ev) {
        ev.preventDefault();
        this.soundEnabled = !this.soundEnabled;
        browser.localStorage.setItem("akd_sound_enabled", this.soundEnabled ? "1" : "0");
        this._applySoundState();
        this._showToast(this.soundEnabled ? "Notification sound ON" : "Notification sound OFF");
    },

    _onViewAll(ev) {
        ev.preventDefault();
        const sid = this.sessionId ? `?session_id=${this.sessionId}` : "";
        window.location.href = `/kitchen/completed${sid}`;
    },

    _onHold(ev) {
        ev.preventDefault();
        this.paused = true;
        this._updateSyncStatus();
        this._updateHoldRecallUI();
        this._showToast("Live updates paused");
    },

    _onRecall(ev) {
        ev.preventDefault();
        this.paused = false;
        this._updateSyncStatus();
        this._updateHoldRecallUI();
        this.loadOrders();
        this._showToast("Live updates resumed");
    },

    _onMore(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const menu = this.el.querySelector("#akd-more-menu");
        if (menu) menu.classList.toggle("open");
    },

    _onBackdropClick(ev) {
        if (ev.target && ev.target.id === "akd-modal-backdrop") {
            this._closeModal();
        }
    },

    _onModalClose(ev) {
        ev.preventDefault();
        this._closeModal();
    },

    _onSearchApply(ev) {
        ev.preventDefault();
        const input = this.el.ownerDocument.querySelector("#akd-search-input");
        this.searchTerm = (input && input.value ? input.value : "").trim().toLowerCase();
        this._closeModal();
        this.renderItems();
        this._showToast(this.searchTerm ? `Search: ${this.searchTerm}` : "Search cleared");
    },

    _onOpenSettings(ev) {
        ev.preventDefault();
        window.location.href = "/web#action=advance_kitchen.action_kitchen_config";
    },

    _onThemeToggle(ev) {
        const checked = !!ev.currentTarget.checked;
        this.theme = checked ? "dark" : "light";
        browser.localStorage.setItem("akd_theme", this.theme);
        this._applyTheme();
    },

    async _onCloseSession(ev) {
        ev.preventDefault();
        try {
            const result = await rpc("/kitchen/session/close", { session_id: this.sessionId });
            if (result && result.success) {
                window.location.href = result.redirect || "/kitchen";
            } else {
                this._showToast(result?.error || "Failed to close session");
            }
        } catch (err) {
            console.error("Kitchen Display: close session failed", err);
            this._showToast("Failed to close session");
        }
    },

    async loadOrders() {
        try {
            const url = this.sessionId ? `/kitchen/orders?session_id=${this.sessionId}` : "/kitchen/orders";
            const response = await fetch(url, {
                method: "GET",
                credentials: "same-origin",
                headers: { Accept: "application/json" },
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const orders = await response.json();
            this.lastSyncAt = new Date();
            this._allOrders = this._buildOrders(orders || []);
            this._notifyForNewItems(this._allOrders);

            const signature = this._computeRenderSignature(this._allOrders);
            if (signature !== this._lastRenderSignature) {
                this._lastRenderSignature = signature;
                this.renderItems();
            }
            const visibleOrders = (this._allOrders || []).filter((order) => !this._isOldCompleted(order));
            this.updateStats(visibleOrders);
            this._updateSyncStatus();
            this._updateStationBadges(this._allOrders);
        } catch (err) {
            console.error("Kitchen Display: failed to load orders", err);
        }
    },

    _buildOrders(orders) {
        const normalizedOrders = [];
        for (const order of orders || []) {
            const lines = [];
            for (const line of order.line_ids || []) {
                const itemState = this._deriveItemState(order, line);
                lines.push({
                    id: line.id,
                    item_state: itemState,
                    quantity: line.quantity,
                    note: line.note,
                    product_name: line.product_name || "Unnamed Item",
                });
            }
            normalizedOrders.push({
                id: order.id,
                order_name: order.name || "",
                order_date: order.order_date,
                table_name: order.table_name || "No Table",
                customer_name: order.customer_name || "Guest",
                station: "all",
                order_state: this._deriveOrderState(order, lines),
                lines,
            });
        }
        return normalizedOrders;
    },

    _computeRenderSignature(orders) {
        return (orders || []).map((order) => [
            order.id,
            order.order_state || "",
            order.order_name || "",
            order.table_name || "",
            order.customer_name || "",
            ...(order.lines || []).map((line) => [
                line.id,
                line.item_state,
                line.quantity,
                line.note || "",
                line.product_name || "",
            ].join("|")),
        ].join("|")).join("||");
    },

    _isCompactLayout() {
        return window.matchMedia("(max-width: 1024px)").matches;
    },

    _getEffectiveStateFilter() {
        if (this._isCompactLayout() && this.activeStateFilter === "all") {
            return "pending";
        }
        return this.activeStateFilter;
    },

    _applyFilters(orders) {
        const search = this.searchTerm;
        const stateFilter = this._getEffectiveStateFilter();
        return (orders || []).filter((order) => {
            if (stateFilter !== "all" && order.order_state !== stateFilter) return false;
            if (this.activeStationFilter !== "all" && order.station !== this.activeStationFilter) return false;
            if (!search) return true;

            const lineSearch = (order.lines || []).map((line) => [line.product_name, line.note].filter(Boolean).join(" ")).join(" ");
            const haystack = [order.order_name, order.table_name, order.customer_name, lineSearch]
                .filter(Boolean)
                .join(" ")
                .toLowerCase();
            return haystack.includes(search);
        });
    },

    renderItems() {
        const container = this.el.querySelector("#akd-board");
        if (!container) return;

        const visibleOrders = (this._allOrders || []).filter((order) => !this._isOldCompleted(order));
        const orders = this._applyFilters(visibleOrders);
        const grouped = { new: [], preparing: [], ready: [], completed: [] };
        for (const order of orders) {
            if (order.order_state === "pending") grouped.new.push(order);
            else if (order.order_state === "in_progress") grouped.preparing.push(order);
            else if (order.order_state === "ready") grouped.ready.push(order);
            else grouped.completed.push(order);
        }

        const completedTotal = grouped.completed.length;
        const completedHiddenCount = Math.max(0, completedTotal - COMPLETED_PREVIEW_LIMIT);
        grouped.completed = grouped.completed.slice(0, COMPLETED_PREVIEW_LIMIT);

        const frag = renderToFragment("advance_kitchen.KitchenBoard", {
            grouped,
            completedTotal,
            completedHiddenCount,
            formatTime: this.formatTime.bind(this),
            stateLabel: this._stateLabel.bind(this),
        });
        container.replaceChildren(frag);
    },

    updateStats(orders) {
        const counts = { all: 0, pending: 0, in_progress: 0, ready: 0, done: 0, cancelled: 0 };
        for (const order of orders || []) {
            counts.all += 1;
            if (order.order_state === "pending") counts.pending += 1;
            else if (order.order_state === "in_progress") counts.in_progress += 1;
            else if (order.order_state === "ready") counts.ready += 1;
            else counts.done += 1;
        }

        this._setText("#tab-count-new", counts.pending);
        this._setText("#tab-count-preparing", counts.in_progress);
        this._setText("#tab-count-ready", counts.ready);
        this._setText("#tab-count-done", counts.done);

        this._setText("#nav-count-all", counts.all);
        this._setText("#nav-count-new", counts.pending);
        this._setText("#nav-count-preparing", counts.in_progress);
        this._setText("#nav-count-ready", counts.ready);
        this._setText("#nav-count-done", counts.done);
        this._setText("#nav-count-cancelled", counts.cancelled);
    },

    _updateStationBadges(orders) {
        this._setText("#nav-count-stations-all", (orders || []).length);
    },

    _updateSyncStatus() {
        const label = this.el.querySelector("#akd-sync-time");
        const dot = this.el.querySelector("#akd-sync-dot");
        if (!label || !dot) return;

        const sessionText = this.sessionStart ? this._formatDuration(Date.now() - this.sessionStart.getTime()) : "--:--:--";
        const syncText = this.lastSyncAt ? this.lastSyncAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--:--";
        const mode = this.paused ? "Paused" : "Live";
        label.textContent = `Session ${sessionText} | Last synced ${syncText} | ${mode}`;
        dot.style.background = this.paused ? "#f59e0b" : "#10b981";
    },

    _updateHoldRecallUI() {
        const holdBtn = this.el.querySelector("#btn-hold");
        const recallBtn = this.el.querySelector("#btn-recall");
        if (!holdBtn || !recallBtn) return;
        holdBtn.style.display = this.paused ? "none" : "";
        recallBtn.style.display = this.paused ? "" : "none";
    },

    _updateFilterUI() {
        const stateFilter = this._getEffectiveStateFilter();
        this.el.setAttribute("data-active-state", stateFilter);
        this.el.querySelectorAll(".akd-nav-item[data-filter-state]").forEach((el) => {
            const state = el.getAttribute("data-filter-state");
            el.classList.toggle("active", state === stateFilter);
        });
        this.el.querySelectorAll(".akd-tab[data-tab-state]").forEach((el) => {
            const state = el.getAttribute("data-tab-state");
            el.classList.toggle("active", state === stateFilter);
        });
        this.el.querySelectorAll(".akd-nav-item[data-filter-station]").forEach((el) => {
            const station = el.getAttribute("data-filter-station");
            el.classList.toggle("active", station === this.activeStationFilter);
        });
    },

    _applySoundState() {
        const btn = this.el.querySelector("#btn-sound");
        if (!btn) return;
        const icon = btn.querySelector("i");
        btn.style.opacity = this.soundEnabled ? "1" : "0.5";
        btn.title = this.soundEnabled ? "Sound ON" : "Sound OFF";
        if (icon) {
            icon.className = this.soundEnabled ? "fa fa-bell" : "fa fa-bell-slash";
        }
    },

    _applyTheme() {
        const body = document.body;
        body.classList.toggle("akd-theme-light", this.theme === "light");
        body.classList.toggle("akd-theme-dark", this.theme !== "light");
        const toggle = this.el.querySelector("#akd-darkmode-toggle");
        if (toggle) toggle.checked = (this.theme !== "light");
    },

    _openModal(type) {
        const doc = this.el.ownerDocument;
        const backdrop = doc.querySelector("#akd-modal-backdrop");
        if (!backdrop) return;
        const target = "#akd-search-modal";
        backdrop.classList.add("open");
        doc.querySelectorAll(".akd-modal").forEach((el) => el.classList.remove("open"));
        const modal = doc.querySelector(target);
        if (modal) modal.classList.add("open");
    },

    _closeModal() {
        const doc = this.el.ownerDocument;
        const backdrop = doc.querySelector("#akd-modal-backdrop");
        if (!backdrop) return;
        backdrop.classList.remove("open");
        doc.querySelectorAll(".akd-modal").forEach((el) => el.classList.remove("open"));
    },

    _showToast(message) {
        const toast = this.el.ownerDocument.querySelector("#akd-toast");
        if (!toast) return;
        toast.textContent = message;
        toast.classList.add("show");
        browser.setTimeout(() => toast.classList.remove("show"), 2200);
    },

    _onGlobalClick(ev) {
        const target = ev.target;
        if (!(target instanceof Element)) return;

        if (target.closest("[data-modal-close]")) {
            ev.preventDefault();
            this._closeModal();
            return;
        }
        if (target.closest("#akd-search-apply")) {
            ev.preventDefault();
            this._onSearchApply(ev);
            return;
        }
        if (target.closest("#akd-open-settings")) {
            ev.preventDefault();
            this._onOpenSettings(ev);
            return;
        }
        if (target.closest("#akd-close-session")) {
            ev.preventDefault();
            this._onCloseSession(ev);
            return;
        }
        const backdrop = target.closest("#akd-modal-backdrop");
        if (backdrop && target.id === "akd-modal-backdrop") {
            ev.preventDefault();
            this._closeModal();
        }
    },

    _onGlobalKeydown(ev) {
        if (ev.key === "Escape") {
            this._closeModal();
            const menu = this.el.querySelector("#akd-more-menu");
            if (menu) menu.classList.remove("open");
        }
    },

    _isOldCompleted(order) {
        if (!order || order.order_state !== "done" || !order.order_date) return false;
        const doneAt = new Date(order.order_date);
        if (Number.isNaN(doneAt.getTime())) return false;
        const ageMs = Date.now() - doneAt.getTime();
        return ageMs > 24 * 60 * 60 * 1000;
    },

    _onDocumentClick(ev) {
        const target = ev.target;
        if (target instanceof Element && this.el.classList.contains("akd-sidebar-open")) {
            const isMobile = window.matchMedia("(max-width: 1024px)").matches;
            if (isMobile) {
                const clickedSidebar = target.closest(".akd-sidebar");
                const clickedToggle = target.closest("#btn-sidebar-toggle");
                if (!clickedSidebar && !clickedToggle) {
                    this.el.classList.remove("akd-sidebar-open");
                }
            }
        }

        const menu = this.el.querySelector("#akd-more-menu");
        const moreWrap = this.el.querySelector(".akd-more-wrap");
        if (!menu || !moreWrap) return;
        if (!moreWrap.contains(ev.target)) {
            menu.classList.remove("open");
        }
    },

    _notifyForNewItems(orders) {
        const incoming = [];
        const nextKnown = new Set();
        for (const order of orders || []) {
            for (const line of (order.lines || [])) {
                nextKnown.add(line.id);
                if (!this._knownPendingLineIds.has(line.id) && line.item_state === "pending") incoming.push(line);
            }
        }
        this._knownPendingLineIds = nextKnown;
        if (!incoming.length) return;

        if (this.soundEnabled) this._playNotificationBeep();
        document.title = `(${incoming.length}) Kitchen Display`;
        this._showToast(`${incoming.length} new item(s) received`);

        if ("Notification" in window && Notification.permission === "granted") {
            const names = incoming.slice(0, 3).map((i) => i.product_name).join(", ");
            new Notification("New kitchen items", { body: names || "New items arrived" });
        }
    },

    _playNotificationBeep() {
        try {
            // Optional custom sound file. If unavailable/blocked, fallback to WebAudio beep.
            const audio = new Audio("/advance_kitchen/static/src/audio/notification.mp3");
            audio.volume = 0.35;
            audio.play().catch(() => this._playFallbackBeep());
        } catch (_) {
            this._playFallbackBeep();
        }
    },

    _playFallbackBeep() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = "sine";
            osc.frequency.value = 880;
            gain.gain.value = 0.03;
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.15);
        } catch (_) {
            // Ignore browsers without audio context access.
        }
    },

    async handleAction(orderId, action) {
        try {
            const result = await rpc(`/kitchen/order/${action}`, { order_id: Number(orderId) });
            if (result && result.success) await this.loadOrders();
        } catch (err) {
            console.error("Kitchen Display: action failed", err);
        }
    },

    async handleLineAction(lineId, action) {
        try {
            const result = await rpc(`/kitchen/line/${action}`, { line_id: Number(lineId) });
            if (result && result.success) await this.loadOrders();
        } catch (err) {
            console.error("Kitchen Display: line action failed", err);
        }
    },

    _deriveItemState(order, line) {
        if (line.state === "done" || line.state === "cancelled") return "done";
        if (line.state === "pending") return "pending";
        if (line.state === "ready") return "ready";
        if (line.state === "cooking") return "in_progress";
        return "pending";
    },

    _deriveOrderState(order, lines) {
        const states = (lines || []).map((line) => line.item_state);
        if (states.length && states.every((state) => state === "done")) return "done";
        if (states.some((state) => state === "in_progress")) return "in_progress";
        if (states.some((state) => state === "pending")) return "pending";
        if (states.some((state) => state === "ready")) return "ready";
        if (order.state === "in_progress") return "in_progress";
        if (order.state === "ready") return "ready";
        if (order.state === "done") return "done";
        return "pending";
    },

    _stateLabel(state) {
        return state === "in_progress" ? "PREPARING" : String(state || "").toUpperCase();
    },

    _formatDuration(ms) {
        const total = Math.max(0, Math.floor(ms / 1000));
        const h = String(Math.floor(total / 3600)).padStart(2, "0");
        const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
        const s = String(total % 60).padStart(2, "0");
        return `${h}:${m}:${s}`;
    },

    _setText(selector, value) {
        const el = this.el.querySelector(selector);
        if (el) el.textContent = String(value);
    },

    formatTime(dateStr) {
        if (!dateStr) return "";
        const date = new Date(dateStr);
        return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    },
});

publicWidget.registry.PosKitchenCompletedPage = publicWidget.Widget.extend({
    selector: "#akd-completed-root",
    events: {
        "submit #akd-completed-search-form": "_onSearchSubmit",
        "click #akd-completed-search-reset": "_onSearchReset",
    },

    init() {
        this._super(...arguments);
        this._bus = null;
        this._channels = [];
        this._busHandler = null;
        this.sessionId = null;
        this.searchTerm = "";
    },

    start() {
        const res = this._super(...arguments);
        this.sessionId = Number(this.el.getAttribute("data-session-id") || 0) || null;
        const input = this.el.querySelector("#akd-completed-search-input");
        this.searchTerm = (input && input.value ? input.value : "").trim();
        this._startBus();
        return res;
    },

    destroy() {
        this._stopBus();
        this._super(...arguments);
    },

    _getBusService() {
        const services = this.env && this.env.services;
        if (!services) return null;
        return services["bus.service"] || services["bus_service"] || null;
    },

    _startBus() {
        const bus = this._getBusService();
        if (!bus) return;
        const channels = [BUS_CHANNEL_ALL];
        if (this.sessionId) channels.push(`${BUS_CHANNEL_ALL}-${this.sessionId}`);
        channels.forEach((ch) => bus.addChannel(ch));
        this._busHandler = async (notifications) => {
            for (const { type } of notifications) {
                if (type === BUS_EVENT_TYPE) {
                    await this._reloadRows();
                    break;
                }
            }
        };
        bus.addEventListener("notification", this._busHandler);
        this._bus = bus;
        this._channels = channels;
    },

    _stopBus() {
        if (!this._bus) return;
        if (this._busHandler) this._bus.removeEventListener("notification", this._busHandler);
        this._channels.forEach((ch) => this._bus.deleteChannel(ch));
        this._bus = null;
        this._channels = [];
        this._busHandler = null;
    },

    async _onSearchSubmit(ev) {
        ev.preventDefault();
        const input = this.el.querySelector("#akd-completed-search-input");
        this.searchTerm = (input && input.value ? input.value : "").trim();
        await this._reloadRows();
    },

    async _onSearchReset(ev) {
        ev.preventDefault();
        this.searchTerm = "";
        const input = this.el.querySelector("#akd-completed-search-input");
        if (input) input.value = "";
        await this._reloadRows();
    },

    async _reloadRows() {
        if (!this.sessionId) return;
        const tbody = this.el.querySelector("#akd-completed-tbody");
        if (!tbody) return;

        const status = this.el.querySelector("#akd-completed-live-status");
        if (status) status.textContent = "Syncing...";

        try {
            const q = encodeURIComponent(this.searchTerm || "");
            const response = await fetch(`/kitchen/completed/items?session_id=${this.sessionId}&q=${q}`, {
                method: "GET",
                credentials: "same-origin",
                headers: { Accept: "application/json" },
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const rows = await response.json();

            tbody.replaceChildren();
            if (!rows.length) {
                const tr = document.createElement("tr");
                const td = document.createElement("td");
                td.colSpan = 6;
                td.className = "akd-completed-empty";
                td.textContent = "No completed items found.";
                tr.appendChild(td);
                tbody.appendChild(tr);
            } else {
                for (const item of rows) {
                    const tr = document.createElement("tr");
                    const values = [
                        item.order_name || "-",
                        item.product_name || "-",
                        item.table_name || "-",
                        item.customer_name || "-",
                        String(item.quantity ?? 0),
                        item.order_date || "-",
                    ];
                    for (const val of values) {
                        const td = document.createElement("td");
                        td.textContent = val;
                        tr.appendChild(td);
                    }
                    tbody.appendChild(tr);
                }
            }
            if (status) status.textContent = "Live updates ON";
        } catch (err) {
            console.error("Kitchen Completed: failed to reload rows", err);
            if (status) status.textContent = "Live updates error";
        }
    },
});
