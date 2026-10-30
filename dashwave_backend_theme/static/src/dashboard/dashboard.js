/** @odoo-module **/
import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";

const ICONS = {
    tasks: "fa-check-square-o", calendar: "fa-calendar", mail: "fa-envelope", approve: "fa-thumbs-o-up",
    check: "fa-check-circle", clock: "fa-clock-o", alert: "fa-exclamation-circle", draft: "fa-file-text-o",
    send: "fa-paper-plane", cart: "fa-shopping-cart", truck: "fa-truck", list: "fa-list-ul", done: "fa-check",
};
const QUOTES = [
    "Small steps every day lead to big results.",
    "Focus on being productive instead of busy.",
    "Great things are done by a series of small things brought together.",
    "Quality is not an act, it is a habit.",
    "The secret of getting ahead is getting started.",
];
const PIE = ["var(--dw-p)", "#3b82f6", "#22c55e", "#f59e0b", "#94a3b8"];

export class DashwaveHome extends Component {
    static template = "dashwave.Home";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.menu = useService("menu");
        this.icons = ICONS;
        this.pie = PIE;
        this.userName = user.name;
        this.userId = user.userId;
        this.state = useState({ d: null, period: "month", year: null, busy: false, q: 0,
                                hover: null, hideRev: false, hideExp: false });
        onWillStart(() => this.load());
        this.timer = setInterval(() => (this.state.q = (this.state.q + 1) % QUOTES.length), 9000);
        onWillUnmount(() => clearInterval(this.timer));
    }

    async load() {
        this.state.busy = true;
        try {
            this.state.d = await rpc("/dashwave/dashboard", { period: this.state.period, year: this.state.year });
            this.state.year = this.state.d.year;
        } finally { this.state.busy = false; }
    }
    setPeriod(ev) { this.state.period = ev.target.value; this.load(); }
    setYear(ev) { this.state.year = Number(ev.target.value); this.load(); }

    /* ── formatting ─────────────────────────────── */
    get greeting() {
        const h = new Date().getHours();
        return h < 12 ? "Good Morning" : h < 17 ? "Good Afternoon" : "Good Evening";
    }
    get quote() { return QUOTES[this.state.q]; }
    nextQuote() { this.state.q = (this.state.q + 1) % QUOTES.length; }
    money(v) {
        const c = this.state.d?.currency || "";
        return `${c} ${Number(v || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    }
    short(v) {
        v = Number(v || 0);
        return v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? Math.round(v / 1e3) + "K" : String(Math.round(v));
    }
    shortDate(s) {
        if (!s) return "";
        const d = new Date(s + "T00:00:00");
        return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }
    get apps() { return this.menu.getApps().filter((a) => a.xmlid !== "dashwave_backend_theme.menu_dashwave_home"); }
    openApp(app) { this.menu.selectMenu(app); }

    /* ── navigation ─────────────────────────────── */
    openList(model, domain, name) {
        if (!model) return;
        this.action.doAction({ type: "ir.actions.act_window", name: name || "Records", res_model: model,
            domain: domain || [], views: [[false, "list"], [false, "form"]] });
    }
    openRecord(model, id) {
        if (model && id) this.action.doAction({ type: "ir.actions.act_window", res_model: model, res_id: id,
            views: [[false, "form"]] });
    }
    openTile(t) {
        if (t.discuss) return this.action.doAction("mail.action_discuss");
        this.openList(t.model, t.domain, t.label);
    }
    openProject(p) { this.openList("project.task", [["project_id", "=", p.id]], p.label); }
    openSalesMonth(i) {
        const s = this.state.d.sales, m = s.series[i];
        this.openList(s.model, [...s.domain, [s.field, ">=", m.from], [s.field, "<", m.to]], `Sales · ${m.label}`);
    }
    openRevExp(i, kind) {
        const r = this.state.d.revexp.ranges[i];
        this.openList("account.move", [["state", "=", "posted"], ["move_type", "=", kind === "rev" ? "out_invoice" : "in_invoice"],
            ["invoice_date", ">=", r[0]], ["invoice_date", "<", r[1]]], `${kind === "rev" ? "Revenue" : "Expenses"} · ${this.state.d.revexp.labels[i]}`);
    }

    /* ── hover / tooltips ───────────────────────── */
    hov(chart, i, text, ev) {
        const box = ev.currentTarget.closest(".dw_card").getBoundingClientRect();
        this.state.hover = { chart, i, text, x: ev.clientX - box.left + 12, y: ev.clientY - box.top - 12 };
    }
    unhov() { this.state.hover = null; }
    isHot(chart, i) { return this.state.hover && this.state.hover.chart === chart && this.state.hover.i === i; }

    /* ── sales area chart (W 460 x H 150) ───────── */
    get salesPts() {
        const s = this.state.d?.sales; if (!s) return [];
        const vals = s.series.map((m) => m.value), max = Math.max(...vals, 1), W = 460, H = 130, n = vals.length - 1;
        return vals.map((v, i) => ({ x: 10 + (i / n) * W, y: 10 + H - (v / max) * H, v, label: s.series[i].label }));
    }
    get salesLine() {
        const p = this.salesPts; if (!p.length) return "";
        return p.map((pt, i) => {
            if (!i) return `M${pt.x},${pt.y}`;
            const q = p[i - 1], cx = (q.x + pt.x) / 2;
            return `C${cx},${q.y} ${cx},${pt.y} ${pt.x},${pt.y}`;
        }).join(" ");
    }
    get salesArea() { const p = this.salesPts; return p.length ? `${this.salesLine} L${p[p.length - 1].x},140 L${p[0].x},140 Z` : ""; }

    /* ── donut ──────────────────────────────────── */
    get donut() {
        const p = this.state.d?.products; if (!p || !p.total) return [];
        const C = 2 * Math.PI * 62; let off = 0;
        return p.items.map((it, i) => {
            const len = (it.value / p.total) * C;
            const seg = { ...it, color: PIE[i % PIE.length], dash: `${Math.max(len - 2, 0.1)} ${C}`, off: -off,
                          pct: Math.round((it.value / p.total) * 100) };
            off += len; return seg;
        });
    }

    /* ── revenue vs expenses bars (W 600 x H 150) ─ */
    get bars() {
        const r = this.state.d?.revexp; if (!r) return null;
        const show = [...(this.state.hideRev ? [] : r.rev), ...(this.state.hideExp ? [] : r.exp)];
        const max = Math.max(...show, 1), H = 190, gw = 600 / r.labels.length;
        const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ y: 210 - f * H, v: this.short(max * f) }));
        return { ticks, groups: r.labels.map((l, i) => ({ l, i, x: 40 + i * gw + gw / 2,
            rh: (r.rev[i] / max) * H, eh: (r.exp[i] / max) * H, rv: r.rev[i], ev: r.exp[i] })) };
    }
}

registry.category("actions").add("dashwave_home", DashwaveHome);
