/** @odoo-module **/
import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService, useBus } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

const HOME_XMLID = "aurora_backend_theme.menu_aurora_home";
const KEY = "aurora.sidebar.collapsed";
const read = () => { try { return localStorage.getItem(KEY) === "1"; } catch { return false; } };

/** Apply the company colours as CSS variables used by the whole theme. */
function applyBrand(b) {
    const r = document.documentElement.style;
    r.setProperty("--aur-p", b.primary);
    r.setProperty("--aur-s", b.secondary);
}

export class AuroraSidebar extends Component {
    static template = "aurora.Sidebar";
    static props = ["*"];

    setup() {
        this.menu = useService("menu");
        this.state = useState({ collapsed: read(), open: {}, fly: null, brand: null, logoOk: true });
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.syncOpen());
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => this.syncOpen());
        onWillStart(async () => {
            try { this.state.brand = await rpc("/aurora/brand"); applyBrand(this.state.brand); } catch {}
        });
        onMounted(() => { this.apply(); this.syncOpen(); });
        onWillUnmount(() => document.body.classList.remove("aurora_sb", "aurora_sb_mini"));
        this.flyTimer = null;
    }

    /* ── data ── */
    get apps() { return this.menu.getApps(); }
    /** The app owning the open action. Odoo falls back to the first app (Home) when an action has no menu in the URL. */
    get currentId() {
        const cur = this.menu.getCurrentApp();
        const act = this.env.services.action?.currentController?.action;
        if (cur && act?.id && !this.owns(cur, act.id)) {
            const app = this.apps.find((x) => this.owns(x, act.id));
            if (app) return app.id;
            // action opened through a server-action menu (no id match): keep the app the user was in, never "Home"
            if (cur.xmlid === HOME_XMLID) return this.lastApp || null;
        }
        return cur?.id;
    }
    owns(app, actionId) {
        const walk = (nodes) => (nodes || []).some((n) => n.actionID === actionId || walk(n.childrenTree));
        return app.actionID === actionId || walk(this.tree(app));
    }
    get logoUrl() { return this.state.brand ? `/web/binary/company_logo?company=${this.state.brand.id}` : null; }
    tree(app) { return this.menu.getMenuAsTree(app.id).childrenTree || []; }
    hasKids(app) { return this.tree(app).length > 0; }

    /* ── layout ── */
    apply() {
        document.body.classList.add("aurora_sb");
        document.body.classList.toggle("aurora_sb_mini", this.state.collapsed);
    }
    toggle() {
        this.state.collapsed = !this.state.collapsed;
        this.state.fly = null;
        try { localStorage.setItem(KEY, this.state.collapsed ? "1" : "0"); } catch {}
        this.apply();
    }
    syncOpen() {
        // accordion: the current app is expanded, other apps fold back
        const id = this.currentId;
        if (id && id !== this.lastOpen) {
            for (const app of this.apps) if (app.id !== id) delete this.state.open[app.id];
            this.state.open[id] = true;
            this.lastOpen = id;
            if (this.menu.getMenu(id)?.xmlid !== HOME_XMLID) this.lastApp = id;
        }
        this.render();
    }

    /* ── navigation ── */
    openApp(app) {
        this.state.open[app.id] = true;
        this.state.fly = null;
        this.menu.selectMenu(app);
    }
    toggleOpen(ev, id) { ev.stopPropagation(); this.state.open[id] = !this.state.open[id]; }
    clickMenu(m) {
        if (m.actionID) { this.state.fly = null; this.menu.selectMenu(m); }
        else this.state.open[m.id] = !this.state.open[m.id];
    }

    /* ── collapsed-mode flyout ── */
    showFly(ev, app) {
        if (!this.isMini()) return;
        clearTimeout(this.flyTimer);
        const r = ev.currentTarget.getBoundingClientRect();
        this.state.fly = { app, top: Math.min(r.top, window.innerHeight - 120) };
    }
    hideFly() { clearTimeout(this.flyTimer); this.flyTimer = setTimeout(() => (this.state.fly = null), 180); }
    keepFly() { clearTimeout(this.flyTimer); }
    isMini() { return this.state.collapsed || window.innerWidth < 1200; }
}

registry.category("main_components").add("AuroraSidebar", { Component: AuroraSidebar });
