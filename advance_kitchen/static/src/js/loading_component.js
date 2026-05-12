/* =============================================================
   advance_kitchen — Kitchen Loading Page Script
   File: static/src/js/kitchen_loading.js

   Plain vanilla JS wrapped in an IIFE.
   NOT an @odoo-module — this runs on a public HTTP page before
   the Odoo module registry is ready, so imports would fail.
   All state is local; no globals except window.aklRetry which
   the template's retry button calls.
   ============================================================= */

(function () {
    "use strict";

    // ── Read server data from data-attributes ─────────────────
    // QWeb renders: <div id="akl-data" data-kitchen-id="3" data-kitchen-name="Main Kitchen"/>
    let KITCHEN_ID   = 0;
    let KITCHEN_NAME = "";

    function init() {
        const dataEl = document.getElementById("akl-data");
        if (!dataEl) {
            showError("Missing kitchen data. Please go back and try again.");
            return;
        }
        KITCHEN_ID   = Number(dataEl.dataset.kitchenId)   || 0;
        KITCHEN_NAME = dataEl.dataset.kitchenName          || "";

        if (!KITCHEN_ID) {
            showError("Invalid kitchen ID. Please go back and try again.");
            return;
        }

        startSession();
    }

    // ── DOM helpers ───────────────────────────────────────────
    function q(id) { return document.getElementById(id); }

    function setStatus(msg) {
        const el = q("akl-status");
        if (el) el.textContent = msg;
    }

    function showError(msg) {
        const loading = q("akl-loading");
        const error   = q("akl-error");
        if (loading) loading.style.display = "none";
        if (error)   error.classList.add("akl-visible");
        const msgEl = q("akl-error-msg");
        if (msgEl) msgEl.textContent = msg || "Something went wrong.";
    }

    function resetToLoading() {
        const loading = q("akl-loading");
        const error   = q("akl-error");
        if (error)   error.classList.remove("akl-visible");
        if (loading) loading.style.display = "flex";
        setStatus("Starting session…");
    }

    // ── Session opener ────────────────────────────────────────
    async function startSession() {
        resetToLoading();

        try {
            setStatus("Connecting to kitchen…");

            const resp = await fetch("/kitchen/start/session", {
                method:      "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "Accept":       "application/json",
                },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    method:  "call",
                    id:      1,
                    params:  { kitchen_id: KITCHEN_ID },
                }),
            });

            if (!resp.ok) {
                throw new Error(`Server error: HTTP ${resp.status}`);
            }

            const json   = await resp.json();
            const result = json.result;

            if (!result || !result.success) {
                throw new Error(result?.error || "Unknown server error.");
            }

            setStatus("Session ready — opening display…");
            await new Promise((r) => setTimeout(r, 350));
            window.location.href = result.redirect;

        } catch (err) {
            console.error("Kitchen loading:", err);
            showError(err.message);
        }
    }

    // Exposed for the retry button's onclick in the template
    window.aklRetry = startSession;

    // ── Boot ──────────────────────────────────────────────────
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

})();