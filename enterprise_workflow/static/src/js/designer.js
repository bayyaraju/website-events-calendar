/** @odoo-module **/
/**
 * Enterprise Workflow Engine — Visual Designer (Odoo 19 / OWL 3)
 *
 * Mounts on the wf.definition form view when the "Designer" page is open.
 * Communicates with the backend through /wf/api/definition/<id>/designer.
 */

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
// DOC-FIX A: In Odoo 17–19 the "rpc" service was removed. Calling controllers
// is done with the plain `rpc` function imported from @web/core/network/rpc.
// useService("rpc") no longer exists and throws "Unknown service: rpc".
// Ref: https://www.odoo.com/documentation/19.0/developer/reference/frontend/services.html
import { rpc } from "@web/core/network/rpc";

// ── Stage icon map ─────────────────────────────────────────────────────────
const ICONS = {
    start:          "▶",
    normal:         "○",
    approval:       "☑",
    condition:      "◇",
    parallel_split: "⊣",
    parallel_join:  "⊢",
    subprocess:     "⊞",
    end:            "■",
    error:          "⚠",
};

// ── Edge classes by trigger type ───────────────────────────────────────────
const EDGE_CLASS = {
    approval_granted:  "approved",
    approval_rejected: "rejected",
    sla_breach:        "sla_breach",
    auto:              "auto",
};

const EDGE_MARKER = {
    approval_granted:  "url(#wf_arrow_green)",
    approval_rejected: "url(#wf_arrow_red)",
    auto:              "url(#wf_arrow_blue)",
};

// ── Component ──────────────────────────────────────────────────────────────
export class WfDesigner extends Component {
    static template = "enterprise_workflow.WfDesigner";

    setup() {
        // DOC-FIX A (continued): Remove useService("rpc") — it no longer
        // exists. The module-level `rpc` import is used directly instead.
        this.orm          = useService("orm");
        this.notification = useService("notification");
        this.canvasOuter  = useRef("canvasOuter");

        this.state = useState({
            loading:         true,
            stages:          [],
            transitions:     [],
            defId:           null,
            defState:        "draft",
            zoom:            1,
            panX:            60,
            panY:            60,
            selectedNode:    null,
            selectedEdge:    null,
            propertiesStage: null,
            connecting:      false,
            fromNodeId:      null,
            tempEnd:         null,
            ctxMenu:         null,
            isPanning:       false,
        });

        this._panStart  = null;
        this._dragState = null;
        this._keyDown   = null;

        onMounted(async () => {
            await this._load();
            this._bindKeys();
        });

        onWillUnmount(() => {
            if (this._keyDown) document.removeEventListener("keydown", this._keyDown);
        });
    }

    // ── Data loading ─────────────────────────────────────────────────────────
    async _load() {
        const placeholder = document.getElementById("wf_designer_canvas");
        if (!placeholder) { this.state.loading = false; return; }

        const defId = parseInt(placeholder.dataset.defId || "0");
        if (!defId) { this.state.loading = false; return; }

        this.state.defId    = defId;
        this.state.defState = placeholder.dataset.state || "draft";

        try {
            // DOC-FIX A (call site): plain function call, no `this.` prefix.
            const d = await rpc(`/wf/api/definition/${defId}/designer`, {});
            if (d.error) throw new Error(d.error);
            this.state.stages      = d.stages      || [];
            this.state.transitions = d.transitions || [];
            this.state.defState    = d.state;

            // FIX: call the real public method autoLayout(), not the
            // non-existent _autoLayout() (TypeError on every fresh workflow).
            if (this.state.stages.length && !this.state.stages.some(s => s.pos_x || s.pos_y)) {
                this.autoLayout();
            }
        } catch (e) {
            this.notification.add("Failed to load designer: " + e.message, { type: "danger" });
        }
        this.state.loading = false;
    }

    _bindKeys() {
        this._keyDown = (e) => {
            if (["INPUT","TEXTAREA","SELECT"].includes(e.target.tagName)) return;
            if (e.key === "Delete" && this.state.selectedNode) {
                this.deleteNode(this.state.selectedNode);
            }
            if (e.key === "Escape") {
                this.state.ctxMenu    = null;
                this.state.connecting = false;
                this.state.fromNodeId = null;
                this.state.tempEnd    = null;
            }
            if ((e.ctrlKey || e.metaKey) && e.key === "s") {
                e.preventDefault();
                this.saveLayout();
            }
        };
        document.addEventListener("keydown", this._keyDown);
    }

    // ── Canvas events ─────────────────────────────────────────────────────────
    onCanvasDown(e) {
        if (e.target.closest(".o_wf_node") || e.target.closest(".o_wf_ctx_menu")) return;
        this._panStart = { x: e.clientX - this.state.panX, y: e.clientY - this.state.panY };
        this.state.isPanning       = true;
        this.state.ctxMenu         = null;
        // Clear selection on background click so highlights don't linger during pan.
        this.state.selectedNode    = null;
        this.state.selectedEdge    = null;
        this.state.propertiesStage = null;
    }

    onMouseMove(e) {
        if (this.state.isPanning && this._panStart) {
            this.state.panX = e.clientX - this._panStart.x;
            this.state.panY = e.clientY - this._panStart.y;
        }
        if (this.state.connecting && this.canvasOuter.el) {
            const r = this.canvasOuter.el.getBoundingClientRect();
            this.state.tempEnd = {
                x: (e.clientX - r.left - this.state.panX) / this.state.zoom,
                y: (e.clientY - r.top  - this.state.panY) / this.state.zoom,
            };
        }
        if (this._dragState) {
            const r = this.canvasOuter.el?.getBoundingClientRect();
            if (!r) return;
            const cx = (e.clientX - r.left - this.state.panX) / this.state.zoom;
            const cy = (e.clientY - r.top  - this.state.panY) / this.state.zoom;
            const s  = this._stageById(this._dragState.id);
            if (s) {
                s.pos_x = Math.max(0, this._dragState.ox + cx - this._dragState.mx);
                s.pos_y = Math.max(0, this._dragState.oy + cy - this._dragState.my);
            }
        }
    }

    onMouseUp() {
        this.state.isPanning = false;
        this._panStart = null;
        if (this._dragState) {
            const s = this._stageById(this._dragState.id);
            if (s) {
                this.orm.write("wf.stage", [s.id], {
                    pos_x: Math.round(s.pos_x),
                    pos_y: Math.round(s.pos_y),
                }).catch(() => {});
            }
            this._dragState = null;
        }
        if (this.state.connecting) {
            this.state.connecting = false;
            this.state.fromNodeId = null;
            this.state.tempEnd    = null;
        }
    }

    onWheel(e) {
        // Prevent the page from scrolling while the user zooms the canvas.
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newZ  = Math.min(Math.max(this.state.zoom * delta, 0.2), 3);
        const r     = this.canvasOuter.el?.getBoundingClientRect();
        if (r) {
            const mx = e.clientX - r.left;
            const my = e.clientY - r.top;
            this.state.panX = mx - (mx - this.state.panX) * (newZ / this.state.zoom);
            this.state.panY = my - (my - this.state.panY) * (newZ / this.state.zoom);
        }
        this.state.zoom = newZ;
    }

    onCanvasClick() {
        this.state.selectedNode    = null;
        this.state.selectedEdge    = null;
        this.state.propertiesStage = null;
    }

    onContextMenu(e) {
        // Suppress the browser's native context menu.
        e.preventDefault();
        const nodeEl = e.target.closest(".o_wf_node");
        const r      = this.canvasOuter.el?.getBoundingClientRect();
        this.state.ctxMenu = {
            x:      e.clientX,
            y:      e.clientY,
            wx:     r ? (e.clientX - r.left - this.state.panX) / this.state.zoom : 200,
            wy:     r ? (e.clientY - r.top  - this.state.panY) / this.state.zoom : 200,
            nodeId: nodeEl ? parseInt(nodeEl.dataset.id) : null,
        };
    }

    // ── Node events ───────────────────────────────────────────────────────────
    onNodeDown(stageId, e) {
        // Stop propagation so onCanvasDown does not clear the selection we set.
        e.stopPropagation();
        this.state.selectedNode    = stageId;
        this.state.propertiesStage = this._stageById(stageId);
        this.state.ctxMenu         = null;

        if (this.state.defState !== "draft") return;

        const s = this._stageById(stageId);
        const r = this.canvasOuter.el?.getBoundingClientRect();
        if (!s || !r) return;

        this._dragState = {
            id: stageId,
            mx: (e.clientX - r.left - this.state.panX) / this.state.zoom,
            my: (e.clientY - r.top  - this.state.panY) / this.state.zoom,
            ox: s.pos_x,
            oy: s.pos_y,
        };
    }

    onPortDown(stageId, e) {
        if (this.state.defState !== "draft") return;
        // Stop propagation: prevents onNodeDown from setting _dragState,
        // which would trigger a spurious ORM write when the mouse is released.
        e.stopPropagation();
        this._dragState       = null;
        this.state.connecting = true;
        this.state.fromNodeId = stageId;
        const s = this._stageById(stageId);
        this.state.tempEnd = { x: (s?.pos_x || 0) + 170, y: (s?.pos_y || 0) + 40 };
    }

    onPortUp(stageId, e) {
        // Stop propagation so onMouseUp does not clear connecting state before
        // _createTransition is called.
        e.stopPropagation();
        if (!this.state.connecting) return;
        const fromId = this.state.fromNodeId;
        if (fromId && fromId !== stageId) {
            this._createTransition(fromId, stageId);
        }
        this.state.connecting = false;
        this.state.fromNodeId = null;
        this.state.tempEnd    = null;
    }

    selectEdge(id) {
        this.state.selectedEdge    = id;
        this.state.selectedNode    = null;
        this.state.propertiesStage = null;
    }

    // ── CRUD operations ───────────────────────────────────────────────────────
    async addStage(type = "normal") {
        const name = prompt("Stage name:");
        if (!name) return;
        await this._createStageAt(name, type,
            Math.round((-this.state.panX + 300) / this.state.zoom),
            Math.round((-this.state.panY + 200) / this.state.zoom));
    }

    async addStageAt(type, x, y) {
        const name = prompt("Stage name:");
        if (!name) return;
        await this._createStageAt(name, type, Math.round(x), Math.round(y));
    }

    async _createStageAt(name, type, x, y) {
        try {
            const ids = await this.orm.create("wf.stage", [{
                definition_id: this.state.defId,
                name,
                code:       name.toLowerCase().replace(/\W+/g, "_"),
                stage_type: type,
                pos_x: x,
                pos_y: y,
            }]);
            // FIX: use stage_type (not "type") so icons and layout helpers work
            // correctly for newly created stages without requiring a page reload.
            this.state.stages.push({
                id: ids[0], name,
                stage_type: type,
                pos_x: x, pos_y: y, sla_hours: 0,
            });
        } catch (e) {
            this.notification.add(e.message, { type: "danger" });
        }
    }

    async deleteNode(id) {
        if (!confirm("Delete this stage and its transitions?")) return;
        try {
            await this.orm.unlink("wf.stage", [id]);
            this.state.stages      = this.state.stages.filter(s => s.id !== id);
            this.state.transitions = this.state.transitions.filter(
                t => t.from_stage_id !== id && t.to_stage_id !== id);
            this.state.selectedNode    = null;
            this.state.propertiesStage = null;
        } catch (e) {
            this.notification.add(e.message, { type: "danger" });
        }
    }

    async _createTransition(fromId, toId) {
        if (this.state.transitions.find(
                t => t.from_stage_id === fromId && t.to_stage_id === toId)) {
            this.notification.add("Transition already exists.", { type: "warning" });
            return;
        }
        const from = this._stageById(fromId);
        const to   = this._stageById(toId);
        const name = `${from?.name || "?"} → ${to?.name || "?"}`;
        try {
            const ids = await this.orm.create("wf.transition", [{
                definition_id: this.state.defId,
                name, from_stage_id: fromId, to_stage_id: toId,
                trigger_type: "manual", condition_type: "none",
            }]);
            this.state.transitions.push({
                id: ids[0], name,
                from_stage_id: fromId, to_stage_id: toId,
                trigger_type: "manual",
            });
        } catch (e) {
            this.notification.add(e.message, { type: "danger" });
        }
    }

    async saveLayout() {
        const positions = {};
        for (const s of this.state.stages) {
            positions[s.id] = { x: Math.round(s.pos_x), y: Math.round(s.pos_y) };
        }
        try {
            // DOC-FIX A (call site): plain rpc() function, no `this.`.
            await rpc(`/wf/api/definition/${this.state.defId}/designer/save`,
                      { positions, canvas_data: {} });
            this.notification.add("Layout saved.", { type: "success" });
        } catch (e) {
            this.notification.add("Save failed.", { type: "warning" });
        }
    }

    openStageForm(id) {
        const base = window.location.origin;
        window.open(`${base}/odoo/workflow/stage/${id}`, "_blank");
    }

    // ── Layout ────────────────────────────────────────────────────────────────
    autoLayout() {
        const stages = this.state.stages;
        if (!stages.length) return;
        // FIX: filter on s.stage_type (not s.type); s.type is always undefined.
        const starts = stages.filter(s => s.stage_type === "start");
        const ends   = stages.filter(s => s.stage_type === "end");
        const mid    = stages.filter(s => s.stage_type !== "start" && s.stage_type !== "end");

        const cols = [starts, ...this._chunks(mid, 3), ends].filter(g => g.length);
        cols.forEach((group, ci) => {
            group.forEach((stage, ri) => {
                stage.pos_x = 80  + ci * 220;
                stage.pos_y = 80  + ri * 130 - ((group.length - 1) * 130) / 2 + 200;
            });
        });
        this.saveLayout();
    }

    fitScreen() {
        if (!this.state.stages.length) return;
        const outer = this.canvasOuter.el;
        if (!outer) return;
        const pad    = 80;
        const minX   = Math.min(...this.state.stages.map(s => s.pos_x))       - pad;
        const maxX   = Math.max(...this.state.stages.map(s => s.pos_x + 160)) + pad;
        const minY   = Math.min(...this.state.stages.map(s => s.pos_y))       - pad;
        const maxY   = Math.max(...this.state.stages.map(s => s.pos_y + 80))  + pad;
        // Guard: avoid division by zero when all stages share a coordinate.
        const contentW = maxX - minX || 1;
        const contentH = maxY - minY || 1;
        const z = Math.min(outer.clientWidth / contentW, outer.clientHeight / contentH, 1.5);
        this.state.zoom = z;
        this.state.panX = -minX * z + (outer.clientWidth  - contentW * z) / 2;
        this.state.panY = -minY * z + (outer.clientHeight - contentH * z) / 2;
    }

    zoomIn()    { this.state.zoom = Math.min(this.state.zoom * 1.2, 3); }
    zoomOut()   { this.state.zoom = Math.max(this.state.zoom * 0.8, 0.2); }
    resetView() { this.state.zoom = 1; this.state.panX = 60; this.state.panY = 60; }

    // ── Template helpers ──────────────────────────────────────────────────────
    transformStyle() {
        return `transform:translate(${this.state.panX}px,${this.state.panY}px) `
             + `scale(${this.state.zoom}); transform-origin:0 0;`;
    }

    nodeStyle(s) { return `left:${s.pos_x}px;top:${s.pos_y}px;`; }

    stageIcon(type) { return ICONS[type] || "○"; }

    edgePath(tr) {
        const from = this._stageById(tr.from_stage_id);
        const to   = this._stageById(tr.to_stage_id);
        if (!from || !to) return "";
        const x1 = from.pos_x + 160, y1 = from.pos_y + 40;
        const x2 = to.pos_x,         y2 = to.pos_y   + 40;
        const cx = (x1 + x2) / 2;
        return `M ${x1} ${y1} C ${cx} ${y1} ${cx} ${y2} ${x2} ${y2}`;
    }

    edgeMid(tr) {
        const from = this._stageById(tr.from_stage_id);
        const to   = this._stageById(tr.to_stage_id);
        if (!from || !to) return { x: 0, y: 0 };
        return {
            x: (from.pos_x + 160 + to.pos_x) / 2,
            y: (from.pos_y + 40  + to.pos_y + 40) / 2 - 14,
        };
    }

    edgeClass(tr) {
        let cls = EDGE_CLASS[tr.trigger_type] || "";
        if (this.state.selectedEdge === tr.id) cls += " selected";
        return cls.trim();
    }

    edgeMarker(tr) { return EDGE_MARKER[tr.trigger_type] || "url(#wf_arrow)"; }

    tempEdgePath() {
        const from = this._stageById(this.state.fromNodeId);
        const end  = this.state.tempEnd;
        if (!from || !end) return "";
        return `M ${from.pos_x + 160} ${from.pos_y + 40} L ${end.x} ${end.y}`;
    }

    // ── Private helpers ───────────────────────────────────────────────────────
    _stageById(id) { return this.state.stages.find(s => s.id === id); }

    _chunks(arr, size) {
        const out = [];
        for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
        return out;
    }
}

// ── Registry ──────────────────────────────────────────────────────────────
// DOC-FIX B: Remove the entire manual mountDesigner() / history.pushState
// mount mechanism. It is fundamentally incompatible with Odoo 19 because:
//
//   1. `new owl.App()` bypasses Odoo's service infrastructure entirely — all
//      useService() calls inside the component fail at runtime because the
//      service registry is only wired up through Odoo's own App instance.
//
//   2. The global `owl` variable is not available in Odoo 19 ESM modules;
//      the bundle is strict and tree-shaken. `const { env } = owl` throws
//      ReferenceError on the first navigation.
//
//   3. `Component.env` is not a static API — it only exists on instances,
//      and even then it is the OWL-internal env, not Odoo's service env.
//
//   4. The history.pushState monkey-patch races with Odoo's own router and
//      causes double-mounts on SPA navigation.
//
// The correct Odoo 19 approach per the documentation is:
//   • Register the component in the "actions" registry with the same tag
//     used in the ir.actions.client record. Odoo's action manager handles
//     mounting/unmounting automatically, with full service access.
//   • If the component lives inside a form view page (notebook tab), use a
//     custom field widget (fields registry) or a view widget — not a manual
//     DOM mount.
//
// The main_components registry is for persistent chrome (systray items etc.),
// not page-level components, so that registration is removed as well.

registry.category("actions").add("wf_designer_action", WfDesigner);
