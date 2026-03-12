/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onMounted } from "@odoo/owl";

/* ============================================================
   CHART HELPERS
============================================================ */

function drawLineChart(canvas, labels, values, color, opts = {}) {
    if (!canvas) return;
    const W = (canvas.parentElement ? canvas.parentElement.clientWidth : 0) || 600;
    const H = opts.height || 240;
    canvas.width  = W;
    canvas.height = H;
    if (!values || !values.length) return;

    const pad = { top: 20, right: 16, bottom: 40, left: 60 };
    const ctx  = canvas.getContext("2d");
    ctx.clearRect(0, 0, W, H);

    const max    = Math.max(...values, 1);
    const xSlot  = (W - pad.left - pad.right) / Math.max(labels.length - 1, 1);
    const yScale = H - pad.top - pad.bottom;

    // Grid
    for (let i = 0; i <= 4; i++) {
        const y   = pad.top + (yScale / 4) * i;
        const val = max - (max / 4) * i;
        ctx.beginPath();
        ctx.strokeStyle = "rgba(255,255,255,0.06)";
        ctx.lineWidth = 1;
        ctx.moveTo(pad.left, y);
        ctx.lineTo(W - pad.right, y);
        ctx.stroke();
        ctx.fillStyle   = "rgba(139,148,158,0.8)";
        ctx.font        = "10px 'IBM Plex Mono', monospace";
        ctx.textAlign   = "right";
        const label = opts.isOrders
            ? val.toFixed(0)
            : "$" + (val >= 1000 ? (val / 1000).toFixed(1) + "k" : val.toFixed(0));
        ctx.fillText(label, pad.left - 6, y + 4);
    }

    // X labels
    ctx.font = "10px 'Sora', sans-serif";
    ctx.fillStyle = "rgba(139,148,158,0.7)";
    ctx.textAlign = "center";
    labels.forEach((lbl, i) => {
        if (i % 3 !== 0 && i !== labels.length - 1) return;
        ctx.fillText(lbl, pad.left + xSlot * i, H - 8);
    });

    // Area fill
    const grad = ctx.createLinearGradient(0, pad.top, 0, H - pad.bottom);
    grad.addColorStop(0, color + "33");
    grad.addColorStop(1, color + "00");
    ctx.beginPath();
    values.forEach((v, i) => {
        const x = pad.left + xSlot * i;
        const y = pad.top + yScale - (v / max) * yScale;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.lineTo(pad.left + xSlot * (values.length - 1), H - pad.bottom);
    ctx.lineTo(pad.left, H - pad.bottom);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Smooth line using bezier
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    values.forEach((v, i) => {
        const x = pad.left + xSlot * i;
        const y = pad.top + yScale - (v / max) * yScale;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Dots
    values.forEach((v, i) => {
        const x = pad.left + xSlot * i;
        const y = pad.top + yScale - (v / max) * yScale;
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = "#0d1117";
        ctx.lineWidth = 1.5;
        ctx.stroke();
    });
}

function drawDonut(canvas, data, colors) {
    if (!canvas || !data || !data.length) return;
    const size = canvas.offsetWidth || 160;
    canvas.width  = size;
    canvas.height = size;
    const ctx   = canvas.getContext("2d");
    ctx.clearRect(0, 0, size, size);
    const total = data.reduce((s, d) => s + (d.value || 0), 0);
    if (!total) return;
    const COLORS = colors || ["#a78bfa","#60a5fa","#34d399","#fbbf24","#f87171","#6b7280"];
    const cx = size/2, cy = size/2;
    const R  = size/2 - 8, r = R * 0.60;
    let angle = -Math.PI / 2;
    data.forEach((d, i) => {
        const slice = ((d.value || 0) / total) * Math.PI * 2;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, R, angle, angle + slice);
        ctx.closePath();
        ctx.fillStyle = COLORS[i % COLORS.length];
        ctx.fill();
        angle += slice;
    });
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = "#0d1117";
    ctx.fill();
    ctx.fillStyle = "#f0f6fc";
    ctx.font = `bold ${Math.round(size * 0.17)}px 'IBM Plex Mono', monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(total, cx, cy);
}

/* ============================================================
   HELPERS
============================================================ */
const STATUS_CLASS = {
    completed: "s-completed", processing: "s-processing", "on-hold": "s-on-hold",
    pending: "s-pending", cancelled: "s-cancelled", refunded: "s-refunded", failed: "s-failed",
    synced: "s-synced", "pending-sync": "s-pending-sync", error: "s-error",
    instock: "s-instock", outofstock: "s-outofstock", onbackorder: "s-onbackorder",
    publish: "s-publish", draft: "s-draft", private: "s-private",
};
const STATUS_DOT = {
    completed:"#34d399", processing:"#60a5fa", "on-hold":"#fbbf24",
    pending:"#8b949e", cancelled:"#f87171", refunded:"#a78bfa", failed:"#f87171",
};
const STOCK_DOT = { instock:"#34d399", outofstock:"#f87171", onbackorder:"#fbbf24" };

/* ============================================================
   COMPONENT
============================================================ */
export class WooDashboardComponent extends Component {
    static template = "woo_connector.Dashboard";

    setup() {
        this.orm          = useService("orm");
        this.notification = useService("notification");
        this.action       = useService("action");

        this.state = useState({
            loading:          true,
            data:             null,
            instances:        [],
            selectedInstance: null,
            activeTab:        "overview",
            couponFilter:     "all",
            productView:      "kanban",   // kanban | table
            error:            null,
            configToggles: {
                sync_images: true,
                create_products: true,
                auto_sync: false,
                sync_stock: true,
            },
        });

        onMounted(async () => {
            await this.loadInstances();
            await this.loadData();
        });
    }

    /* -- Formatting -- */
    formatCurrency(v) {
        if (v === undefined || v === null) return "-";
        return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(v);
    }
    formatNumber(v) {
        if (!v && v !== 0) return "-";
        return new Intl.NumberFormat().format(v);
    }
    statusClass(s)  { return STATUS_CLASS[s] || "s-pending"; }
    statusDot(s)    { return STATUS_DOT[s]   || "#8b949e"; }
    stockDot(s)     { return STOCK_DOT[s]    || "#8b949e"; }
    getKey(obj, k)  { return (obj && obj[k]) || 0; }

    /** Progress bar width % for payment methods */
    pmPct(count) {
        const total = this.state.data && this.state.data.kpis && this.state.data.kpis.total_orders;
        if (!total) return 0;
        return Math.round((count / total) * 100);
    }

    /** Progress bar width % for log levels */
    logPct(count, total) {
        if (!total || !count) return 0;
        return Math.round((count / total) * 100);
    }

    /** Format a float to 2 decimals safely */
    toFixed2(v) {
        if (v === undefined || v === null) return "0.00";
        return parseFloat(v).toFixed(2);
    }

    /** Total log count */
    totalLogs() {
        const ll = this.state.data && this.state.data.log_levels;
        if (!ll) return 0;
        return (ll.success || 0) + (ll.info || 0) + (ll.warning || 0) + (ll.error || 0);
    }

    /** Filter coupons by status */
    setCouponFilter(ev) {
        this.state.couponFilter = ev.target.value;
    }

    filteredCoupons() {
        const all = (this.state.data && this.state.data.coupons) || [];
        const f = this.state.couponFilter;
        if (f === "active")  return all.filter(c => c.status === "active");
        if (f === "expired") return all.filter(c => c.status === "expired" || c.status === "used_up");
        return all;
    }

    couponTypeLabel(t) {
        if (t === "percent")       return "% Off";
        if (t === "fixed_cart")    return "Cart $";
        if (t === "fixed_product") return "Item $";
        return t;
    }

    couponTypeColor(t) {
        if (t === "percent")       return "#a78bfa";
        if (t === "fixed_cart")    return "#60a5fa";
        if (t === "fixed_product") return "#34d399";
        return "#8b949e";
    }

    /** Total queue count */
    totalQueue() {
        const qs = this.state.data && this.state.data.queue_summary;
        if (!qs) return 0;
        return (qs.done || 0) + (qs.draft || 0) + (qs.processing || 0) + (qs.failed || 0);
    }

    /** Safe image fallback - returns placeholder src if url is empty */
    imgOrPlaceholder(url) { return url || ''; }

    syncClass(s) {
        if (s === "synced") return "s-synced";
        if (s === "error")  return "s-error";
        return "s-pending-sync";
    }
    stockClass(s) { return STATUS_CLASS[s] || "s-pending"; }

    /* -- Tab -- */
    setTab(t) {
        this.state.activeTab = t;
        setTimeout(() => this.drawCharts(), 60);
    }
    setTabOverview()  { this.setTab("overview");  }
    setTabOrders()    { this.setTab("orders");     }
    setTabProducts()  { this.setTab("products");   }
    setTabSync()      { this.setTab("sync");       }
    setTabConfig()    { this.setTab("config");     }
    setTabCoupons()   { this.setTab("coupons");    }

    /* -- Product view -- */
    setViewKanban() { this.state.productView = "kanban"; }
    setViewTable()  { this.state.productView = "table";  }

    /* -- Config toggle -- */
    toggleConfig(key) {
        this.state.configToggles[key] = !this.state.configToggles[key];
    }
    toggleSyncImages()   { this.toggleConfig("sync_images"); }
    toggleCreateProds()  { this.toggleConfig("create_products"); }
    toggleAutoSync()     { this.toggleConfig("auto_sync"); }
    toggleSyncStock()    { this.toggleConfig("sync_stock"); }

    /* -- Refresh -- */
    async onRefresh() { await this.loadData(); }

    /* -- Sync now -- */
    async onSyncNow() {
        this.notification.add("Sync started...", { type: "info" });
        await this.loadData();
    }

    /* -- Load instances -- */
    async loadInstances() {
        try {
            const instances = await this.orm.call("woo.dashboard", "get_instances", []);
            this.state.instances = instances || [];
            if (instances && instances.length) this.state.selectedInstance = instances[0].id;
        } catch (e) {
            console.error(e);
            this.notification.add("Failed to load Woo instances", { type: "danger" });
        }
    }

    /* -- Load data -- */
    async loadData() {
        if (!this.state.selectedInstance) return;
        this.state.loading = true;
        this.state.error   = null;
        try {
            const data = await this.orm.call(
                "woo.dashboard", "get_dashboard_data", [this.state.selectedInstance]
            );
            this.state.data    = data;
            this.state.loading = false;
            await new Promise(r => setTimeout(r, 60));
            this.drawCharts();
        } catch (e) {
            console.error(e);
            this.state.loading = false;
            this.state.error   = "Could not load dashboard data.";
            this.notification.add("Error loading dashboard", { type: "danger" });
        }
    }

    /* -- Charts -- */
    drawCharts() {
        const d = this.state.data;
        if (!d) return;
        const sd = [
            { value: (d.stock_status && d.stock_status.instock)     || 0 },
            { value: (d.stock_status && d.stock_status.outofstock)  || 0 },
            { value: (d.stock_status && d.stock_status.onbackorder) || 0 },
        ];
        const stockColors = ["#34d399","#f87171","#fbbf24"];
        if (d.revenue_trend && d.revenue_trend.length) {
            drawLineChart(
                document.getElementById("woo-revenue-chart"),
                d.revenue_trend.map(r => r.month),
                d.revenue_trend.map(r => r.revenue),
                "#a78bfa", { height: 240 }
            );
            drawLineChart(
                document.getElementById("woo-orders-chart"),
                d.revenue_trend.map(r => r.month),
                d.revenue_trend.map(r => r.orders),
                "#60a5fa", { height: 240, isOrders: true }
            );
        }
        if (d.orders_by_status && d.orders_by_status.length) {
            drawDonut(document.getElementById("woo-status-donut"), d.orders_by_status);
        }
        drawDonut(document.getElementById("woo-stock-donut"), sd, stockColors);
        drawDonut(document.getElementById("woo-stock-mini-donut"), sd, stockColors);
    }

    /* -- Instance change -- */
    async onInstanceChange(ev) {
        this.state.selectedInstance = parseInt(ev.target.value);
        await this.loadData();
    }

    /* -- Navigate to Woo config -- */
    openWooConfig() {
        this.setTab("config");
    }
}

registry.category("actions").add("woo_connector.dashboard", WooDashboardComponent);
