/** @odoo-module **/
import { Component, proxy, signal, onWillStart, onMounted, onPatched, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

/* ══════════════════════════════════════════════════════════
   UTILITIES
══════════════════════════════════════════════════════════ */
let _id = 0;
const uid  = () => ++_id;
const ts   = () => new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});
const esc  = s  => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

/* ══════════════════════════════════════════════════════════
   MARKDOWN RENDERER
══════════════════════════════════════════════════════════ */
function renderMd(raw) {
    if (!raw) return markup("");
    // Strip special blocks from display text
    let s = raw
        .replace(/```excel_report[\s\S]*?```/g, "")
        .replace(/```chart_spec[\s\S]*?```/g, "")
        .replace(/```odoo_op[\s\S]*?```/g, "")
        .replace(/```module_install[\s\S]*?```/g, "")
        .replace(/```batch_create[\s\S]*?```/g, "")
        .replace(/```crud_form[\s\S]*?```/g, "");

    // Fenced code blocks
    const blocks = [];
    s = s.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        const langLabel = lang ? `<span class="cl-code-lang">${esc(lang)}</span>` : "";
        blocks.push(`<div class="cl-pre-wrap">${langLabel}<pre class="cl-pre"><code>${esc(code.trim())}</code></pre></div>`);
        return `\x02${blocks.length-1}\x03`;
    });

    s = esc(s);
    s = s.replace(/`([^`\n]+)`/g, '<code class="cl-icode">$1</code>');
    s = s.replace(/^### (.+)$/gm, '<h4 class="cl-h4">$1</h4>');
    s = s.replace(/^## (.+)$/gm,  '<h3 class="cl-h3">$1</h3>');
    s = s.replace(/^# (.+)$/gm,   '<h2 class="cl-h2">$1</h2>');
    s = s.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
    s = s.replace(/\*\*(.+?)\*\*/g,     "<strong>$1</strong>");
    s = s.replace(/\*([^*\n]+)\*/g,     "<em>$1</em>");
    s = s.replace(/~~(.+?)~~/g,         "<del>$1</del>");

    // Tables
    s = s.replace(/((?:[^\n]*\|[^\n]*\n)+)/g, blk => {
        const lines = blk.trim().split("\n").filter(Boolean);
        if (lines.length < 2 || !lines[0].includes("|")) return blk;
        const pr    = l => l.replace(/^\||\|$/g,"").split("|").map(c=>c.trim());
        const isSep = l => /^[\s|:\-]+$/.test(l);
        const hdrs  = pr(lines[0]);
        const rows  = lines.slice(1).filter(l=>!isSep(l)).map(pr);
        let t = '<div class="cl-tbl-wrap"><table class="cl-tbl"><thead><tr>';
        hdrs.forEach(h => { t += `<th>${h}</th>`; });
        t += "</tr></thead><tbody>";
        rows.forEach((r,ri) => {
            t += `<tr class="${ri%2===0?'cl-tr-even':''}">`;
            r.forEach(c => { t += `<td>${c}</td>`; });
            t += "</tr>";
        });
        return t + "</tbody></table></div>";
    });

    // Unordered lists
    s = s.replace(/((?:^[-*•]\s.+(?:\n|$))+)/gm, blk => {
        const lis = blk.trim().split("\n").map(l=>`<li>${l.replace(/^[-*•]\s/,"")}</li>`).join("");
        return `<ul class="cl-ul">${lis}</ul>`;
    });
    // Ordered lists
    s = s.replace(/((?:^\d+[.)]\s.+(?:\n|$))+)/gm, blk => {
        const lis = blk.trim().split("\n").map(l=>`<li>${l.replace(/^\d+[.)]\s/,"")}</li>`).join("");
        return `<ol class="cl-ol">${lis}</ol>`;
    });
    // Blockquotes
    s = s.replace(/((?:^&gt;\s?.+(?:\n|$))+)/gm, blk => {
        const inner = blk.trim().replace(/^&gt;\s?/gm,"");
        return `<blockquote class="cl-bq">${inner}</blockquote>`;
    });
    // Paragraphs
    s = s.split(/\n{2,}/).map(p => {
        p = p.replace(/\n/g,"<br>");
        if (/^\s*<(h[1-6]|ul|ol|pre|div|table|blockquote)/.test(p)) return p;
        return p.trim() ? `<p>${p}</p>` : "";
    }).filter(Boolean).join("");

    s = s.replace(/\x02(\d+)\x03/g, (_, i) => blocks[+i]);
    return markup(s);
}

/* ══════════════════════════════════════════════════════════
   RESULT TABLE FORMATTER
══════════════════════════════════════════════════════════ */
function fmtResult(data, model=null) {
    if (!data) return markup("<em class='cl-empty'>No data returned.</em>");
    if (typeof data === "number") return markup(`<span class="cl-count">🔢 ${data.toLocaleString()} records</span>`);
    if (data && data.error) return markup(`<span class="cl-err-text">⚠️ ${esc(data.error)}</span>`);
    if (data && data.created != null) return markup(`<span class="cl-count">✅ ${data.created} records imported (IDs: ${(data.ids||[]).slice(0,10).join(', ')}${data.ids?.length>10?'...':''})</span>`);
    if (!Array.isArray(data)) return markup(`<pre class="cl-pre">${esc(JSON.stringify(data,null,2))}</pre>`);
    if (!data.length) return markup("<em class='cl-empty'>No records found.</em>");

    const keys = Object.keys(data[0]).filter(k=>k!=="id");
    const openable = !!(model && data[0].id);
    let t = `<div class="cl-tbl-tools"><span class="cl-res-count">📊 ${data.length.toLocaleString()} record${data.length!==1?"s":""}</span>`;
    if (data.length > 1) t += `<input class="cl-tbl-filter" placeholder="🔎 Filter rows…"/>`;
    t += `<span class="cl-tbl-hint">${data.length > 1 ? "Click a column to sort" : ""}${openable ? (data.length > 1 ? " · " : "") + "click a row to open it" : ""}</span>`;
    t += `<button class="cl-tbl-csv" title="Download as CSV">⬇ CSV</button></div>`;
    t += `<div class="cl-tbl-wrap"><table class="cl-tbl cl-itbl"${openable ? ` data-model="${esc(model)}"` : ""}><thead><tr>`;
    keys.forEach((k, ki) => { t += `<th class="cl-sort" data-col="${ki}">${esc(k.replace(/_/g,' '))}<span class="cl-sort-ic"></span></th>`; });
    t += "</tr></thead><tbody>";
    data.slice(0,200).forEach((row,ri) => {
        t += `<tr class="${ri%2===0?'cl-tr-even':''}${openable && row.id ? ' cl-row-open' : ''}"${openable && row.id ? ` data-id="${Number(row.id)}"` : ""}>`;
        keys.forEach(k => {
            let v = row[k];
            if (Array.isArray(v) && v.length===2) v = v[1];
            if (v===false||v===null||v===undefined) v = "—";
            const s = String(v);
            const num = typeof v === "number" ? ` data-n="${v}"` : "";
            t += `<td title="${esc(s)}"${num}>${esc(s.length>60?s.slice(0,59)+'…':s)}</td>`;
        });
        t += "</tr>";
    });
    t += "</tbody></table></div>";
    if (data.length>200) t += `<p class="cl-more">Showing 200 of ${data.length.toLocaleString()} records</p>`;
    return markup(t);
}

/* ══════════════════════════════════════════════════════════
   FILE DOWNLOAD
══════════════════════════════════════════════════════════ */
function downloadXlsx(b64, name) {
    const bin = atob(b64), buf = new Uint8Array(bin.length);
    for (let i=0;i<bin.length;i++) buf[i]=bin.charCodeAt(i);
    const a = Object.assign(document.createElement("a"),{
        href: URL.createObjectURL(new Blob([buf],{type:"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})),
        download: name,
    });
    a.click(); URL.revokeObjectURL(a.href);
}

function fileToB64(file) {
    return new Promise((res,rej) => {
        const fr = new FileReader();
        fr.onload  = () => res(fr.result.split(',')[1]);
        fr.onerror = rej;
        fr.readAsDataURL(file);
    });
}

/* ══════════════════════════════════════════════════════════
   SVG CHART ENGINE — pure SVG, no CDN needed
══════════════════════════════════════════════════════════ */
const PAL  = ["#6366f1","#22d3ee","#f472b6","#34d399","#fb923c","#a78bfa","#38bdf8","#facc15","#4ade80","#f97316"];
const PAL2 = ["#818cf8","#67e8f9","#f9a8d4","#6ee7b7","#fca5a1","#c4b5fd","#7dd3fc","#fde68a","#86efac","#fdba74"];

function mkSvg(w, h) {
    const el = document.createElementNS("http://www.w3.org/2000/svg","svg");
    el.setAttribute("viewBox",`0 0 ${w} ${h}`);
    el.setAttribute("style","width:100%;height:auto;display:block;max-height:340px;");
    return el;
}
function mkEl(tag, attrs, txt) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    if (attrs) for (const [k,v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    if (txt !== undefined && txt !== null) el.textContent = String(txt);
    return el;
}
function numFmt(n) {
    n = Number(n)||0;
    if (Math.abs(n)>=1e9) return (n/1e9).toFixed(1)+"B";
    if (Math.abs(n)>=1e6) return (n/1e6).toFixed(1)+"M";
    if (Math.abs(n)>=1e3) return (n/1e3).toFixed(1)+"K";
    return Number.isInteger(n)?String(n):n.toFixed(1);
}
function shortLbl(s,max=14) { s=String(s||""); return s.length>max?s.slice(0,max-1)+"…":s; }

// ── Bar chart ──────────────────────────────────────────
function renderBar(container, spec) {
    const W=720, H=360, pad={top:50,right:24,bottom:90,left:70};
    const labels   = spec.labels||[];
    const datasets = spec.datasets||[];
    const allVals  = datasets.flatMap(d=>(d.data||[]).map(Number)).filter(isFinite);
    if (!allVals.length) { container.innerHTML='<p style="color:#94a3b8;padding:20px">No data</p>'; return; }
    const rawMax = Math.max(...allVals,0);
    const rawMin = Math.min(...allVals,0);
    const maxV   = rawMax===0&&rawMin===0 ? 1 : rawMax + (rawMax-rawMin)*0.12;
    const minV   = rawMin < 0 ? rawMin - (rawMax-rawMin)*0.05 : 0;
    const range  = maxV - minV || 1;
    const cW     = W - pad.left - pad.right;
    const cH     = H - pad.top  - pad.bottom;
    const n      = Math.max(labels.length,1);
    const ds     = Math.max(datasets.length,1);
    const grpW   = cW / n;
    const barW   = Math.min(Math.max(grpW/(ds+0.6), 8), 48);

    const svg = mkSvg(W,H);
    // Background
    svg.appendChild(mkEl("rect",{x:0,y:0,width:W,height:H,rx:12,fill:"#0d1117"}));
    // Title
    if (spec.title) svg.appendChild(mkEl("text",{x:W/2,y:26,"text-anchor":"middle","font-size":"14","font-weight":"700",fill:"#e2e8f0","font-family":"system-ui"},spec.title));

    const g = mkEl("g",{transform:`translate(${pad.left},${pad.top})`});
    svg.appendChild(g);

    // Grid + Y labels
    const ticks = 6;
    for (let i=0;i<=ticks;i++) {
        const v = minV + range*i/ticks;
        const y = cH - (v-minV)/range*cH;
        g.appendChild(mkEl("line",{x1:0,y1:y.toFixed(1),x2:cW,y2:y.toFixed(1),stroke:"#1e293b","stroke-width":"1"}));
        g.appendChild(mkEl("text",{x:-8,y:(y+4).toFixed(1),"text-anchor":"end","font-size":"10",fill:"#64748b","font-family":"system-ui"},numFmt(v)));
    }
    // Zero line
    if (minV < 0 && maxV > 0) {
        const zy = (cH - (0-minV)/range*cH).toFixed(1);
        g.appendChild(mkEl("line",{x1:0,y1:zy,x2:cW,y2:zy,stroke:"#475569","stroke-width":"1.5","stroke-dasharray":"4,2"}));
    }

    // Bars
    labels.forEach((lbl,i) => {
        const cx = (i+0.5)*grpW;
        datasets.forEach((d,di) => {
            const val  = Number((d.data||[])[i])||0;
            const color= d.backgroundColor || PAL[di%PAL.length];
            const bh   = Math.abs(val)/range*cH;
            const zy   = cH*(maxV-minV<=0?1:(maxV/range));
            const by   = val>=0 ? zy-bh : zy;
            const bx   = cx - (ds*barW)/2 + di*barW;
            const rect = mkEl("rect",{x:bx.toFixed(1),y:by.toFixed(1),width:(barW*0.85).toFixed(1),height:Math.max(bh,1).toFixed(1),fill:color,rx:"3",class:"cl-pt cl-bar","data-i":i,"data-d":di});
            g.appendChild(rect);
            // Value label on bar
            if (bh > 14) {
                g.appendChild(mkEl("text",{x:(bx+barW*0.425).toFixed(1),y:(val>=0?by-3:by+bh+11).toFixed(1),"text-anchor":"middle","font-size":"9",fill:color,"font-weight":"600","font-family":"system-ui"},numFmt(val)));
            }
        });
        // X label
        g.appendChild(mkEl("text",{x:cx.toFixed(1),y:(cH+18).toFixed(1),"text-anchor":"middle","font-size":"10",fill:"#94a3b8","font-family":"system-ui"},shortLbl(lbl,12)));
    });

    // Y-axis label
    const yLabel = mkEl("text",{transform:`rotate(-90)`,x:(-cH/2).toFixed(1),y:-52,"text-anchor":"middle","font-size":"11",fill:"#64748b","font-family":"system-ui"},datasets[0]?.label||"");
    g.appendChild(yLabel);

    // Legend
    datasets.forEach((d,i) => {
        const lx = 10 + i*150;
        const ly = cH + 40;
        if (lx > cW-20) return;
        g.appendChild(mkEl("rect",{x:lx,y:ly,width:12,height:12,fill:d.backgroundColor||PAL[i%PAL.length],rx:"2"}));
        g.appendChild(mkEl("text",{x:lx+16,y:ly+10,"font-size":"10",fill:"#94a3b8","font-family":"system-ui"},shortLbl(d.label||`Series ${i+1}`,16)));
    });

    container.innerHTML=""; container.appendChild(svg);
}

// ── Line chart ─────────────────────────────────────────
function renderLine(container, spec) {
    const W=720, H=360, pad={top:50,right:24,bottom:90,left:70};
    const labels   = spec.labels||[];
    const datasets = spec.datasets||[];
    const allVals  = datasets.flatMap(d=>(d.data||[]).map(Number)).filter(isFinite);
    if (!allVals.length) { container.innerHTML='<p style="color:#94a3b8;padding:20px">No data</p>'; return; }
    const maxV = Math.max(...allVals)*1.12||1;
    const minV = Math.min(Math.min(...allVals)*0.9, 0);
    const range= maxV-minV||1;
    const cW   = W-pad.left-pad.right;
    const cH   = H-pad.top-pad.bottom;
    const n    = Math.max(labels.length-1,1);

    const svg = mkSvg(W,H);
    svg.appendChild(mkEl("rect",{x:0,y:0,width:W,height:H,rx:12,fill:"#0d1117"}));
    if (spec.title) svg.appendChild(mkEl("text",{x:W/2,y:26,"text-anchor":"middle","font-size":"14","font-weight":"700",fill:"#e2e8f0","font-family":"system-ui"},spec.title));
    const g = mkEl("g",{transform:`translate(${pad.left},${pad.top})`});
    svg.appendChild(g);

    for (let i=0;i<=5;i++) {
        const v = minV+range*i/5;
        const y = (cH-(v-minV)/range*cH).toFixed(1);
        g.appendChild(mkEl("line",{x1:0,y1:y,x2:cW,y2:y,stroke:"#1e293b","stroke-width":"1"}));
        g.appendChild(mkEl("text",{x:-8,y:String(Number(y)+4),"text-anchor":"end","font-size":"10",fill:"#64748b","font-family":"system-ui"},numFmt(v)));
    }

    datasets.forEach((d,di) => {
        const color = d.borderColor || d.backgroundColor || PAL[di%PAL.length];
        const pts = (d.data||[]).map((v,i)=>[i/n*cW, cH-(Number(v)-minV)/range*cH]);
        if (pts.length<2) return;

        // Area fill
        const fillColor = PAL2[di%PAL2.length]+"33";
        const areaD = `M${pts[0][0].toFixed(1)},${cH.toFixed(1)} ` + pts.map(p=>`L${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ") + ` L${pts[pts.length-1][0].toFixed(1)},${cH.toFixed(1)} Z`;
        g.appendChild(mkEl("path",{d:areaD,fill:fillColor}));

        // Line
        const pathD = pts.map((p,i)=>(i===0?"M":"L")+p[0].toFixed(1)+","+p[1].toFixed(1)).join(" ");
        g.appendChild(mkEl("path",{d:pathD,fill:"none",stroke:color,"stroke-width":"2.5","stroke-linejoin":"round","stroke-linecap":"round"}));

        // Dots
        pts.forEach(([px,py],i) => {
            g.appendChild(mkEl("circle",{cx:px.toFixed(1),cy:py.toFixed(1),r:"4.5",fill:color,stroke:"#0d1117","stroke-width":"2",class:"cl-pt cl-dotp","data-i":i,"data-d":di}));
            g.appendChild(mkEl("circle",{cx:px.toFixed(1),cy:py.toFixed(1),r:"14",fill:"transparent",class:"cl-hit","data-i":i,"data-d":di}));
        });
    });

    labels.forEach((lbl,i) => {
        const x = (i/n*cW).toFixed(1);
        g.appendChild(mkEl("text",{x,y:(cH+18).toFixed(1),"text-anchor":"middle","font-size":"10",fill:"#94a3b8","font-family":"system-ui"},shortLbl(lbl,12)));
    });

    datasets.forEach((d,i) => {
        const lx = 10+i*150; const ly = cH+40;
        if (lx>cW-20) return;
        g.appendChild(mkEl("rect",{x:lx,y:ly,width:12,height:12,fill:d.borderColor||d.backgroundColor||PAL[i%PAL.length],rx:"2"}));
        g.appendChild(mkEl("text",{x:lx+16,y:ly+10,"font-size":"10",fill:"#94a3b8","font-family":"system-ui"},shortLbl(d.label||`Series ${i+1}`,16)));
    });

    container.innerHTML=""; container.appendChild(svg);
}

// ── Extended colour palette for many slices ────────────
const PAL_EXT = [
    "#6366f1","#22d3ee","#f472b6","#34d399","#fb923c",
    "#a78bfa","#38bdf8","#facc15","#4ade80","#f97316",
    "#e879f9","#2dd4bf","#fbbf24","#60a5fa","#f87171",
    "#a3e635","#818cf8","#67e8f9","#86efac","#fde68a",
];

// ── Build pie SVG — pure SVG, no HTML fallback ──────────
function buildPieSvg(spec, W, H) {
    const isDoughnut = spec.type === "doughnut";
    const d0     = (spec.datasets || [])[0] || {};
    const vals   = (d0.data || []).map(Number).filter(isFinite);
    const labels = spec.labels || [];
    if (!vals.length) return null;

    const total = vals.reduce((a, b) => a + Math.abs(b), 0) || 1;
    const cx = W / 2, cy = H / 2;
    const r  = Math.min(cx, cy) - 24;
    const ir = r * 0.50;   // inner radius for doughnut

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    svg.style.cssText = "width:100%;height:100%;display:block;";

    // Dark background
    svg.appendChild(mkEl("rect", {x:0,y:0,width:W,height:H,rx:0,fill:"#0d1117"}));

    // Title
    if (spec.title) {
        svg.appendChild(mkEl("text", {
            x: W/2, y: 22,
            "text-anchor":"middle","font-size":"15","font-weight":"700",
            fill:"#e2e8f0","font-family":"system-ui,-apple-system,sans-serif"
        }, spec.title));
    }

    // Slices
    let angle = -Math.PI / 2;
    vals.forEach((v, i) => {
        const slice = Math.abs(v) / total * 2 * Math.PI;
        const midA  = angle + slice / 2;
        const color = PAL_EXT[i % PAL_EXT.length];

        const x1 = cx + r * Math.cos(angle);
        const y1 = cy + r * Math.sin(angle);
        const x2 = cx + r * Math.cos(angle + slice);
        const y2 = cy + r * Math.sin(angle + slice);
        const large = slice > Math.PI ? 1 : 0;

        let pathD;
        if (isDoughnut) {
            const ix1 = cx + ir * Math.cos(angle + slice);
            const iy1 = cy + ir * Math.sin(angle + slice);
            const ix2 = cx + ir * Math.cos(angle);
            const iy2 = cy + ir * Math.sin(angle);
            pathD = `M${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${large},1 ${x2.toFixed(2)},${y2.toFixed(2)} L${ix1.toFixed(2)},${iy1.toFixed(2)} A${ir},${ir} 0 ${large},0 ${ix2.toFixed(2)},${iy2.toFixed(2)} Z`;
        } else {
            pathD = `M${cx},${cy} L${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${large},1 ${x2.toFixed(2)},${y2.toFixed(2)} Z`;
        }

        const path = mkEl("path", {d:pathD, fill:color, stroke:"#0d1117", "stroke-width":"2", class:"cl-pt cl-slice", "data-i":i, "data-d":0});
        svg.appendChild(path);

        // % label inside slice (only if slice is wide enough)
        const pct = (Math.abs(v) / total * 100);
        if (slice > 0.25 && pct >= 2) {
            const labR = isDoughnut ? (r + ir) / 2 : r * 0.62;
            const lx = cx + labR * Math.cos(midA);
            const ly = cy + labR * Math.sin(midA);
            svg.appendChild(mkEl("text", {
                x: lx.toFixed(1), y: (ly + 4).toFixed(1),
                "text-anchor":"middle","font-size":"11","font-weight":"700",
                fill:"#fff","font-family":"system-ui"
            }, pct.toFixed(1) + "%"));
        }
        angle += slice;
    });

    // Doughnut centre
    if (isDoughnut) {
        svg.appendChild(mkEl("text", {
            x: cx, y: (cy - 6).toFixed(1),
            "text-anchor":"middle","font-size":"16","font-weight":"800",
            fill:"#e2e8f0","font-family":"system-ui"
        }, numFmt(total)));
        svg.appendChild(mkEl("text", {
            x: cx, y: (cy + 14).toFixed(1),
            "text-anchor":"middle","font-size":"10",
            fill:"#64748b","font-family":"system-ui"
        }, "Total"));
    }

    return svg;
}

// ── Build scrollable HTML legend ────────────────────────
function buildLegendHtml(spec) {
    const d0     = (spec.datasets || [])[0] || {};
    const vals   = (d0.data || []).map(Number).filter(isFinite);
    const labels = spec.labels || [];
    const total  = vals.reduce((a, b) => a + Math.abs(b), 0) || 1;

    let html = '<div class="cl-legend-list">';
    vals.forEach((v, i) => {
        const color = PAL_EXT[i % PAL_EXT.length];
        const pct   = (Math.abs(v) / total * 100).toFixed(1);
        const lbl   = String(labels[i] || `Item ${i+1}`);
        html += `
            <div class="cl-legend-row cl-pt" data-i="${i}" data-d="0">
                <span class="cl-legend-dot" style="background:${color}"></span>
                <span class="cl-legend-name" title="${esc(lbl)}">${esc(lbl)}</span>
                <span class="cl-legend-val">${numFmt(v)}</span>
                <span class="cl-legend-pct">${pct}%</span>
            </div>`;
    });
    html += '</div>';
    return html;
}

// ── Render pie into a container (thumbnail size) ────────
function renderPie(container, spec) {
    const d0   = (spec.datasets || [])[0] || {};
    const vals = (d0.data || []).map(Number).filter(isFinite);
    if (!vals.length) {
        container.innerHTML = '<p style="color:#94a3b8;padding:20px">No data</p>';
        return;
    }

    // Layout: SVG left, legend right (scrollable)
    container.innerHTML = `
        <div class="cl-pie-wrap">
            <div class="cl-pie-svg-box"></div>
            <div class="cl-pie-legend">${buildLegendHtml(spec)}</div>
        </div>`;

    const svgBox = container.querySelector(".cl-pie-svg-box");
    const svg    = buildPieSvg(spec, 340, 300);
    if (svg) svgBox.appendChild(svg);

    // Store spec on element for modal reuse
    container._chartSpec = spec;
}

// ── Dispatch ───────────────────────────────────────────
function renderInto(el, spec) {
    const type = String(spec.type || "bar").toLowerCase();
    if (type === "pie" || type === "doughnut" || type === "polararea") renderPie(el, spec);
    else if (type === "line" || type === "area") renderLine(el, spec);
    else renderBar(el, spec);
}

const PERIOD_CHIPS = [["month","1M"],["3m","3M"],["6m","6M"],["12m","12M"],["ytd","YTD"],["all","All"]];
const GRAN_CHIPS   = [["week","Week"],["month","Month"],["quarter","Quarter"]];

function saveBlob(blob, name) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
const csvCell = v => { const s = String(v ?? ""); return /[",\n;]/.test(s) ? `"${s.replace(/"/g,'""')}"` : s; };
const slug = s => String(s || "chart").replace(/[^\w]+/g, "_").replace(/^_|_$/g, "").toLowerCase() || "chart";

function chartCsv(spec) {
    const ds = spec.datasets || [];
    const lines = [["Label", ...ds.map(d => d.label || "Value")].map(csvCell).join(",")];
    (spec.labels || []).forEach((l, i) => lines.push([l, ...ds.map(d => (d.data || [])[i])].map(csvCell).join(",")));
    saveBlob(new Blob(["﻿" + lines.join("\n")], {type: "text/csv"}), slug(spec.title) + ".csv");
}

function chartPng(plot, spec) {
    const svg = plot.querySelector("svg");
    if (!svg) return;
    const vb = (svg.getAttribute("viewBox") || "0 0 720 360").split(/\s+/).map(Number);
    const xml = new XMLSerializer().serializeToString(svg);
    const img = new Image();
    img.onload = () => {
        const c = document.createElement("canvas");
        c.width = vb[2] * 2; c.height = vb[3] * 2;
        const ctx = c.getContext("2d"); ctx.fillStyle = "#0d1117"; ctx.fillRect(0, 0, c.width, c.height);
        ctx.drawImage(img, 0, 0, c.width, c.height);
        c.toBlob(b => b && saveBlob(b, slug(spec.title) + ".png"));
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
}

/** Interactive chart: toolbar (type, sort, period, granularity, CSV/PNG), tooltips,
 *  hover highlight and click-to-open-records. hooks = {drill(spec,i), requery(spec,opts)} */
function drawChart(id, spec, hooks = {}) {
    try {
        const el = document.getElementById(id);
        if (!el || el._cDone) return;
        el._cDone = true;
        el.innerHTML = `<div class="cl-ctb"></div><div class="cl-plot"></div><div class="cl-tip"></div>`;
        const tb = el.querySelector(".cl-ctb"), plot = el.querySelector(".cl-plot"), tip = el.querySelector(".cl-tip");
        const st = {
            period: spec.src?.period || null,
            gran: (spec.src?.groupby || "").split(":")[1] || null,
            sorted: false, busy: false,
        };
        const canDrill = () => !!(spec.drill && spec.keys && hooks.drill);
        const btn = (act, val, label, on, title="") =>
            `<button class="cl-cb${on ? " on" : ""}" data-act="${act}" data-val="${val}" title="${esc(title)}">${label}</button>`;

        const paintToolbar = () => {
            const t = String(spec.type || "bar").toLowerCase();
            let h = `<div class="cl-cgrp">${btn("type","bar","▮ Bar",t==="bar","Bar chart")}${btn("type","line","📈 Line",t==="line"||t==="area","Line chart")}${btn("type","pie","◔ Pie",t==="pie"||t==="doughnut","Pie chart")}</div>`;
            if (t === "bar" && !spec.src?.is_date) h += `<div class="cl-cgrp">${btn("sort","1",st.sorted?"A→Z":"↓ Value",false,"Sort")}</div>`;
            if (spec.src?.date_field && hooks.requery)
                h += `<div class="cl-cgrp">${PERIOD_CHIPS.map(([v,l]) => btn("period",v,l,st.period===v,"Period")).join("")}</div>`;
            if (spec.src?.is_date && hooks.requery)
                h += `<div class="cl-cgrp">${GRAN_CHIPS.map(([v,l]) => btn("gran",v,l,st.gran===v,"Group by")).join("")}</div>`;
            h += `<div class="cl-cgrp cl-cgrp-r">${btn("csv","1","⬇ CSV",false,"Download data as CSV")}${btn("png","1","⬇ PNG",false,"Download chart image")}</div>`;
            if (canDrill()) h += `<div class="cl-chint">💡 Click a bar, point or slice to open its records</div>`;
            tb.innerHTML = h;
        };
        const paint = () => { renderInto(plot, spec); plot.classList.toggle("cl-drill", canDrill()); paintToolbar(); };

        const requery = async (opts) => {
            if (st.busy || !hooks.requery) return;
            st.busy = true; plot.classList.add("cl-busy");
            try {
                const res = await hooks.requery(spec, {period: st.period, granularity: st.gran, chart_type: spec.type, ...opts});
                if (res && res.spec) {
                    Object.assign(spec, res.spec);
                    if (opts.period) st.period = opts.period;
                    if (opts.granularity) st.gran = opts.granularity;
                }
            } finally { st.busy = false; plot.classList.remove("cl-busy"); paint(); }
        };

        tb.addEventListener("click", (ev) => {
            const b = ev.target.closest(".cl-cb"); if (!b) return;
            const {act, val} = b.dataset;
            if (act === "type") { spec.type = val; paint(); }
            else if (act === "sort") {
                st.sorted = !st.sorted;
                const idx = (spec.labels || []).map((_, i) => i);
                const d0 = (spec.datasets?.[0]?.data) || [];
                idx.sort(st.sorted ? (a, b2) => String(spec.labels[a]).localeCompare(String(spec.labels[b2]))
                                   : (a, b2) => (Number(d0[b2]) || 0) - (Number(d0[a]) || 0));
                spec.labels = idx.map(i => spec.labels[i]);
                if (spec.keys) spec.keys = idx.map(i => spec.keys[i]);
                spec.datasets = spec.datasets.map(d => ({...d, data: idx.map(i => d.data[i])}));
                paint();
            }
            else if (act === "period") requery({period: val});
            else if (act === "gran") requery({granularity: val});
            else if (act === "csv") chartCsv(spec);
            else if (act === "png") chartPng(plot, spec);
        });

        const hot = (i) => {
            plot.querySelectorAll(".cl-hot").forEach(n => n.classList.remove("cl-hot"));
            if (i == null) { plot.classList.remove("cl-dim"); return; }
            plot.classList.add("cl-dim");
            plot.querySelectorAll(`.cl-pt[data-i="${i}"]`).forEach(n => n.classList.add("cl-hot"));
        };
        plot.addEventListener("mousemove", (ev) => {
            const n = ev.target.closest("[data-i]");
            if (!n || !plot.contains(n)) { tip.style.display = "none"; hot(null); return; }
            const i = Number(n.dataset.i), di = Number(n.dataset.d || 0);
            const d = (spec.datasets || [])[di] || {};
            const v = Number((d.data || [])[i]) || 0;
            const tot = (d.data || []).reduce((a, b2) => a + Math.abs(Number(b2) || 0), 0) || 1;
            tip.innerHTML = `<b>${esc(spec.labels[i])}</b><span>${esc(d.label || "Value")}: <b>${v.toLocaleString(undefined,{maximumFractionDigits:2})}</b></span><span class="cl-tip-pct">${(Math.abs(v)/tot*100).toFixed(1)}% of total</span>${canDrill() ? '<span class="cl-tip-go">Click to open records →</span>' : ""}`;
            const r = el.getBoundingClientRect();
            let x = ev.clientX - r.left + 14, y = ev.clientY - r.top + 14;
            tip.style.display = "flex";
            if (x + tip.offsetWidth > r.width) x = ev.clientX - r.left - tip.offsetWidth - 14;
            tip.style.left = x + "px"; tip.style.top = y + "px";
            hot(i);
        });
        plot.addEventListener("mouseleave", () => { tip.style.display = "none"; hot(null); });
        plot.addEventListener("click", (ev) => {
            const n = ev.target.closest("[data-i]");
            if (n && canDrill()) hooks.drill(spec, Number(n.dataset.i));
        });
        paint();
    } catch(e) { console.error("Chart render error:", e); }
}

// ── Fullscreen modal ────────────────────────────────────
function openChartModal(spec) {
    // Remove any existing modal
    document.getElementById("cl-modal-overlay")?.remove();

    const overlay = document.createElement("div");
    overlay.id = "cl-modal-overlay";
    overlay.className = "cl-modal-overlay";

    const box = document.createElement("div");
    box.className = "cl-modal-box";

    // Header
    const hdr = document.createElement("div");
    hdr.className = "cl-modal-hdr";
    hdr.innerHTML = `
        <span class="cl-modal-title">${esc(spec.title || "Chart")}</span>
        <div class="cl-modal-hdr-btns">
            <button class="cl-modal-dl" title="Download SVG">⬇ Save</button>
            <button class="cl-modal-close" title="Close (Esc)">✕</button>
        </div>`;
    box.appendChild(hdr);

    // Body — big SVG left, legend right
    const body = document.createElement("div");
    body.className = "cl-modal-body";

    const svgWrap = document.createElement("div");
    svgWrap.className = "cl-modal-svg-wrap";
    const type = String(spec.type || "bar").toLowerCase();
    if (type === "pie" || type === "doughnut" || type === "polararea") {
        const bigSvg = buildPieSvg(spec, 560, 480);
        if (bigSvg) {
            bigSvg.style.cssText = "width:100%;height:100%;display:block;";
            svgWrap.appendChild(bigSvg);
        }
    } else {
        // For bar/line just re-render into a temp container
        const tmp = document.createElement("div");
        tmp.style.cssText = "width:680px;height:420px;";
        if (type === "line" || type === "area") renderLine(tmp, spec);
        else renderBar(tmp, spec);
        const s = tmp.querySelector("svg");
        if (s) { s.style.cssText="width:100%;height:100%;"; svgWrap.appendChild(s); }
    }
    body.appendChild(svgWrap);

    // Legend panel
    const lgWrap = document.createElement("div");
    lgWrap.className = "cl-modal-legend";
    lgWrap.innerHTML = buildLegendHtml(spec);
    body.appendChild(lgWrap);

    box.appendChild(body);
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    // Close handlers
    const close = () => overlay.remove();
    overlay.addEventListener("click", e => { if (e.target === overlay) close(); });
    box.querySelector(".cl-modal-close").addEventListener("click", close);
    document.addEventListener("keydown", function esc(e) {
        if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
    });

    // Download SVG
    box.querySelector(".cl-modal-dl").addEventListener("click", () => {
        const svgEl = svgWrap.querySelector("svg");
        if (!svgEl) return;
        const blob = new Blob([svgEl.outerHTML], {type:"image/svg+xml"});
        const a = Object.assign(document.createElement("a"), {
            href: URL.createObjectURL(blob),
            download: (spec.title || "chart").replace(/\s+/g,"_") + ".svg"
        });
        a.click(); URL.revokeObjectURL(a.href);
    });
}


/* ══════════════════════════════════════════════════════════
   CRUD FORM MODAL — create / edit / delete records
══════════════════════════════════════════════════════════ */
function openCrudModal(spec, onSubmit) {
    document.getElementById("cl-crud-overlay")?.remove();

    const action = spec.action || "create";
    const title  = spec.title  || (action === "create" ? "Create Record" : action === "write" ? "Edit Record" : "Delete Record");
    const fields = spec.fields || [];

    const overlay = document.createElement("div");
    overlay.id = "cl-crud-overlay";
    overlay.className = "cl-modal-overlay";

    const box = document.createElement("div");
    box.className = "cl-modal-box cl-crud-box";

    // Header
    const hdr = document.createElement("div");
    hdr.className = "cl-modal-hdr";
    const icon = action === "create" ? "✚" : action === "write" ? "✎" : "✕";
    hdr.innerHTML = `<span class="cl-modal-title">${icon} ${esc(title)}</span>
        <button class="cl-modal-close" title="Close">✕</button>`;
    box.appendChild(hdr);

    // Form body
    const body = document.createElement("div");
    body.className = "cl-crud-body";

    if (action === "unlink") {
        body.innerHTML = `<div class="cl-crud-warning">
            <span class="cl-crud-warn-icon">⚠️</span>
            <p>Are you sure you want to <strong>permanently delete</strong> this record?</p>
            <p class="cl-crud-warn-sub">Model: <code>${esc(spec.model)}</code> · ID: <code>${spec.id}</code></p>
            <p class="cl-crud-warn-sub">This action <strong>cannot be undone.</strong></p>
        </div>`;
    } else {
        const fieldHtml = fields.map(f => {
            const val = f.value !== undefined ? esc(String(f.value)) : (f.default !== undefined ? esc(String(f.default)) : "");
            const req = f.required ? ' <span class="cl-crud-req">*</span>' : "";
            let input;
            if (f.type === "boolean") {
                const checked = f.value ? "checked" : "";
                input = `<input type="checkbox" name="${esc(f.name)}" class="cl-crud-check" ${checked}/>`;
            } else if (f.type === "text") {
                input = `<textarea name="${esc(f.name)}" class="cl-crud-textarea" placeholder="${esc(f.label)}" rows="3">${val}</textarea>`;
            } else if (f.type === "selection" && f.options) {
                const opts = f.options.map(o => `<option value="${esc(o[0])}" ${f.value == o[0] ? "selected" : ""}>${esc(o[1])}</option>`).join("");
                input = `<select name="${esc(f.name)}" class="cl-crud-select"><option value="">— Select —</option>${opts}</select>`;
            } else if (f.type === "date") {
                input = `<input type="date" name="${esc(f.name)}" class="cl-crud-input" value="${val}"/>`;
            } else if (f.type === "integer" || f.type === "float" || f.type === "monetary") {
                input = `<input type="number" name="${esc(f.name)}" class="cl-crud-input" value="${val}" step="${f.type === "integer" ? "1" : "0.01"}"/>`;
            } else {
                input = `<input type="text" name="${esc(f.name)}" class="cl-crud-input" value="${val}" placeholder="${esc(f.placeholder || f.label)}"/>`;
            }
            return `<div class="cl-crud-field">
                <label class="cl-crud-label">${esc(f.label)}${req}</label>
                ${input}
                ${f.help ? `<p class="cl-crud-help">${esc(f.help)}</p>` : ""}
            </div>`;
        }).join("");
        body.innerHTML = `<div class="cl-crud-fields">${fieldHtml}</div>`;
    }
    box.appendChild(body);

    // Footer
    const footer = document.createElement("div");
    footer.className = "cl-crud-footer";
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "cl-btn-skip cl-crud-cancel";
    cancelBtn.textContent = "Cancel";
    const submitBtn = document.createElement("button");
    submitBtn.className = action === "unlink" ? "cl-crud-btn-delete" : "cl-btn-exec cl-crud-submit";
    submitBtn.textContent = action === "create" ? "✚ Create" : action === "write" ? "✔ Save Changes" : "🗑 Delete Permanently";
    footer.appendChild(cancelBtn);
    footer.appendChild(submitBtn);
    box.appendChild(footer);

    overlay.appendChild(box);
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    cancelBtn.addEventListener("click", close);
    overlay.addEventListener("click", e => { if (e.target === overlay) close(); });
    box.querySelector(".cl-modal-close").addEventListener("click", close);
    document.addEventListener("keydown", function escKey(e) {
        if (e.key === "Escape") { close(); document.removeEventListener("keydown", escKey); }
    });

    submitBtn.addEventListener("click", () => {
        let vals = {};
        if (action !== "unlink") {
            const inputs = body.querySelectorAll("[name]");
            inputs.forEach(inp => {
                const name = inp.getAttribute("name");
                if (inp.type === "checkbox") vals[name] = inp.checked;
                else if (inp.type === "number") vals[name] = inp.value !== "" ? Number(inp.value) : null;
                else vals[name] = inp.value;
            });
            // Validate required
            const missing = fields.filter(f => f.required && !vals[f.name]);
            if (missing.length) {
                missing.forEach(f => {
                    const inp = body.querySelector(`[name="${f.name}"]`);
                    if (inp) { inp.style.borderColor = "#ef4444"; setTimeout(() => inp.style.borderColor = "", 2000); }
                });
                return;
            }
        }
        close();
        if (onSubmit) onSubmit(vals);
    });
}

/* ══════════════════════════════════════════════════════════
   QUICK CREATE PANEL — floating action button
══════════════════════════════════════════════════════════ */
const QUICK_CREATE_TEMPLATES = {
    customer: {
        action: "create", model: "res.partner", title: "New Customer",
        fields: [
            {name:"name",   label:"Customer Name", type:"char", required:true},
            {name:"email",  label:"Email",          type:"char"},
            {name:"phone",  label:"Phone",           type:"char"},
            {name:"street", label:"Street",          type:"char"},
            {name:"city",   label:"City",            type:"char"},
            {name:"customer_rank", label:"Is Customer", type:"integer", default:1},
        ]
    },
    product: {
        action: "create", model: "product.template", title: "New Product",
        fields: [
            {name:"name",       label:"Product Name",  type:"char",      required:true},
            {name:"list_price", label:"Sales Price",   type:"monetary",  default:0},
            {name:"default_code",label:"Internal Reference", type:"char"},
            {name:"type",       label:"Type",          type:"selection",
             options:[["consu","Consumable"],["service","Service"],["storable","Storable Product"]]},
        ]
    },
    invoice: {
        action: "create", model: "account.move", title: "New Invoice",
        fields: [
            {name:"partner_id",  label:"Customer ID",   type:"integer", required:true, help:"Enter the partner's numeric ID"},
            {name:"move_type",   label:"Type",           type:"selection",
             options:[["out_invoice","Customer Invoice"],["out_refund","Credit Note"]], default:"out_invoice"},
            {name:"invoice_date",label:"Invoice Date",   type:"date"},
            {name:"ref",         label:"Reference",      type:"char"},
        ]
    },
    employee: {
        action: "create", model: "hr.employee", title: "New Employee",
        fields: [
            {name:"name",       label:"Employee Name",   type:"char", required:true},
            {name:"work_email", label:"Work Email",       type:"char"},
            {name:"job_title",  label:"Job Title",        type:"char"},
            {name:"mobile_phone",label:"Mobile",          type:"char"},
        ]
    },
};

/* ══════════════════════════════════════════════════════════
   OWL COMPONENT
══════════════════════════════════════════════════════════ */
class ClaudeChatWidget extends Component {
    static template = "claude_ai.ChatWidget";

    setup() {
        this.notif  = useService("notification");
        this.action = useService("action");
        this.msgEl  = signal.ref();
        this.fileEl = signal.ref();
        this.state  = proxy({
            msgs:[], input:"", loading:false,
            sessionId:null, totalTokens:0, modelName:"", hasKey:false,
            dark: true,
            attachments: [],   // [{name, b64, type}]
            showAttachPrev: false,
            suggestions: [],
            savings: null,
        });
        onWillStart(() => this._boot());
        this.chartHooks = {
            drill: (spec, i) => this._drill(spec, i),
            requery: (spec, opts) => rpc("/claude_ai/chart_data", {src: spec.src, ...opts}).then(r => {
                if (r.error) { this.notif.add(r.error, {type: "danger"}); return null; }
                return r;
            }),
        };
        onMounted(()  => { this._scroll(); this._bindTables(); });
        onPatched(()  => {
            this.state.msgs.forEach(m => {
                if (m.chartSpec && m.chartId && !m._cDrawn) {
                    m._cDrawn = true;
                    requestAnimationFrame(() => requestAnimationFrame(() => drawChart(m.chartId, m.chartSpec, this.chartHooks)));
                }
            });
        });
    }

    async _boot() {
        try {
            const cfg = await rpc("/claude_ai/config");
            if (!cfg.error) {
                this.state.modelName=cfg.model_name||""; this.state.hasKey=cfg.has_api_key;
                this.state.savings=cfg.savings||null;
            }
            const s = await rpc("/claude_ai/session");
            if (s.session_id) this.state.sessionId=s.session_id;
        } catch(e) { console.error("boot:",e); }

        if (!this.state.hasKey) {
            this._push("assistant","⚠️ **API key not configured.**\n\nGo to **Claude AI → Configuration**, enter your Anthropic API key and click Save.\n\n⚡ Meanwhile the **Quick Actions** and simple questions (*show customers*, *how many invoices*, *install crm module*) already work – they are answered locally, for free.");
        } else {
            this._push("assistant",
                "👋 **Hello! I'm your Odoo AI Assistant.**\n\n" +
                "I have **full access** to your live database and can:\n\n" +
                "| Capability | Example |\n" +
                "|---|---|\n" +
                "| 📊 **Query & display data** | *Show unpaid invoices over $1000* |\n" +
                "| 📈 **Charts** | *Pie chart of sales by category* |\n" +
                "| 📋 **Excel reports** | *Monthly sales report as spreadsheet* |\n" +
                "| ✏️ **Create/update records** | *Create customer John Doe* |\n" +
                "| 📦 **Install modules** | *Install the CRM module* |\n" +
                "| 📁 **Import from files** | *Upload a CSV to import customers* |\n" +
                "| 💬 **Odoo guidance** | *How do I set up a price list?* |\n\n" +
                "What would you like to do?"
            );
        }
    }

    _push(role, text, extras={}) {
        const m = {
            id: uid(), role, text, time: ts(), status:"done",
            html:         renderMd(text),
            userHtml:     role==="user" ? markup(`<span>${esc(text).replace(/\n/g,"<br>")}</span>`) : null,
            excel:        extras.excel_b64      || null,
            excelName:    extras.excel_filename || "report.xlsx",
            chartSpec:    extras.chart_spec     || null,
            chartId:      extras.chart_spec     ? `ch${uid()}` : null,
            _cDrawn:      false,
            op:           extras.odoo_op        || null,
            opResult:     extras.op_result      || null,
            opResultHtml: extras.op_result!=null ? fmtResult(extras.op_result, extras.odoo_op?.model) : null,
            needsConfirm: extras.needs_confirmation || false,
            confirmed:false, cancelled:false,
            showResult:   extras.op_result!=null,
            installResult: extras.install_result || null,
            batchResult:   extras.batch_result   || null,
            crudForm:      extras.crud_form       || null,
            attachNames:  extras.attachNames     || [],
            source:       extras.source          || null,
            tokens:       extras.tokens_used     || 0,
            refresh:      extras.refresh_needed  || false,
            executing:    false,
        };
        this.state.msgs.push(m);
        this._scroll();
        return m;
    }

    /* ── Interactive charts & tables ──────────────────── */
    _feed() { return this.msgEl.el || (typeof this.msgEl === "function" ? this.msgEl() : null); }

    _openRecords(model, domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window", name, res_model: model, domain,
            views: [[false, "list"], [false, "form"]], target: "new",
        });
    }

    _drill(spec, i) {
        const d = spec.drill || {}, key = (spec.keys || [])[i], f = d.field;
        if (!d.model || !f) return;
        let cond;
        if (key && typeof key === "object" && key.from) cond = [[f, ">=", key.from], [f, "<", key.to]];
        else if (key === null || key === undefined || key === false) cond = [[f, "=", false]];
        else cond = [[f, "=", key]];
        this._openRecords(d.model, [...(d.domain || []), ...cond], `${(spec.title || "").split(" (")[0]} · ${spec.labels[i]}`);
    }

    _bindTables() {
        const feed = this._feed();
        if (!feed || feed._tblBound) return;
        feed._tblBound = true;
        feed.addEventListener("click", (ev) => {
            const th = ev.target.closest("th.cl-sort");
            if (th) return this._sortTable(th);
            const csv = ev.target.closest(".cl-tbl-csv");
            if (csv) return this._tableCsv(csv);
            const tr = ev.target.closest("tr.cl-row-open");
            if (tr) {
                const model = tr.closest("table").dataset.model;
                if (model) this.action.doAction({type: "ir.actions.act_window", res_model: model,
                    res_id: Number(tr.dataset.id), views: [[false, "form"]], target: "new"});
            }
        });
        feed.addEventListener("input", (ev) => {
            const inp = ev.target.closest(".cl-tbl-filter");
            if (!inp) return;
            const q = inp.value.trim().toLowerCase();
            const tbl = inp.closest(".cl-result-body, .cl-result-panel")?.querySelector("table.cl-itbl");
            if (!tbl) return;
            let n = 0;
            tbl.querySelectorAll("tbody tr").forEach(r => {
                const show = !q || r.textContent.toLowerCase().includes(q);
                r.style.display = show ? "" : "none"; if (show) n++;
            });
            const cnt = inp.parentElement.querySelector(".cl-res-count");
            if (cnt) cnt.textContent = q ? `📊 ${n} matching` : `📊 ${tbl.tBodies[0].rows.length} records`;
        });
    }

    _sortTable(th) {
        const tbl = th.closest("table"), col = Number(th.dataset.col);
        const dir = th.dataset.dir === "asc" ? "desc" : "asc";
        tbl.querySelectorAll("th.cl-sort").forEach(h => { delete h.dataset.dir; h.classList.remove("cl-asc", "cl-desc"); });
        th.dataset.dir = dir; th.classList.add(dir === "asc" ? "cl-asc" : "cl-desc");
        const body = tbl.tBodies[0], rows = [...body.rows];
        const val = r => { const c = r.cells[col]; return c?.dataset.n != null ? Number(c.dataset.n) : (c?.textContent || "").toLowerCase(); };
        rows.sort((a, b) => { const x = val(a), y = val(b); const c = (typeof x === "number" && typeof y === "number") ? x - y : String(x).localeCompare(String(y), undefined, {numeric: true}); return dir === "asc" ? c : -c; });
        rows.forEach((r, i) => { r.classList.toggle("cl-tr-even", i % 2 === 0); body.appendChild(r); });
    }

    _tableCsv(btn) {
        const tbl = btn.closest(".cl-result-body, .cl-result-panel")?.querySelector("table.cl-itbl");
        if (!tbl) return;
        const head = [...tbl.tHead.rows[0].cells].map(c => csvCell(c.textContent.trim()));
        const rows = [...tbl.tBodies[0].rows].filter(r => r.style.display !== "none")
            .map(r => [...r.cells].map(c => csvCell(c.dataset.n ?? c.getAttribute("title") ?? c.textContent)).join(","));
        saveBlob(new Blob(["\ufeff" + [head.join(","), ...rows].join("\n")], {type: "text/csv"}), "odoo_records.csv");
    }

    _getMsgById(id) { return this.state.msgs.find(m=>m.id===Number(id)); }
    _scroll() { setTimeout(()=>{ const el=this.msgEl(); if(el) el.scrollTop=9e9; },80); }

    /* ── Handlers ────────────────────────────────────── */
    toggleTheme() { this.state.dark=!this.state.dark; }
    onKeyDown(ev) { if(ev.key==="Enter"&&!ev.shiftKey){ev.preventDefault();this.send();} }

    onExpandChart(ev) {
        const m = this._getMsgById(ev.currentTarget.dataset.msgid);
        if (m && m.chartSpec) openChartModal(m.chartSpec);
    }

    onQuickAsk(ev) {
        const q = ev.currentTarget.dataset.q;
        if (q) { this.state.input=q; this.send(ev.currentTarget.dataset.key || null); }
    }

    onRefresh(ev) {
        if (ev.currentTarget.dataset.mode === "reload") {
            window.location.reload();
        } else {
            // reload the action stack (other open views) without leaving the chat
            this.action.doAction("soft_reload");
            this.notif.add("Views refreshed.", {type: "info"});
        }
    }

    onToggleResult(ev) {
        const m = this._getMsgById(ev.currentTarget.dataset.msgid);
        if (m) m.showResult=!m.showResult;
    }

    onDlExcel(ev) {
        const m = this._getMsgById(ev.currentTarget.dataset.msgid);
        if (m&&m.excel) downloadXlsx(m.excel,m.excelName);
    }

    async onConfirmOp(ev) {
        const m = this._getMsgById(ev.currentTarget.dataset.msgid);
        if (!m) return;
        if (m.executing) return;
        m.executing=true;
        try {
            const r = await rpc("/claude_ai/execute",{operation:m.op});
            m.executing=false;
            m.confirmed=true;
            if (r.success) {
                m.opResult=r.result; m.opResultHtml=fmtResult(r.result, m.op?.model); m.showResult=true;
                m.refresh=r.refresh_needed||false;
                this.notif.add("✅ Operation executed successfully!",{type:"success"});
            } else { this._push("assistant",`❌ **Error:** ${r.error}`); }
        } catch(e) { m.executing=false; this._push("assistant",`❌ ${e}`); }
        this._scroll();
    }
    onCancelOp(ev) { const m=this._getMsgById(ev.currentTarget.dataset.msgid); if(m) m.cancelled=true; }

    /* ── File attachment ─────────────────────────────── */
    onAttachClick() {
        const f=this.fileEl(); if (f) f.click();
    }

    async onFileChange(ev) {
        const files = Array.from(ev.target.files||[]);
        if (!files.length) return;
        for (const f of files) {
            try {
                const b64 = await fileToB64(f);
                this.state.attachments.push({name:f.name, b64, type:f.type, size:f.size});
            } catch(e) { console.error("File read error:",e); }
        }
        ev.target.value=""; // reset
    }

    removeAttachment(ev) {
        const idx = Number(ev.currentTarget.dataset.idx);
        this.state.attachments.splice(idx,1);
    }

    /* ── Send ────────────────────────────────────────── */
    async send(quickKey=null) {
        if (quickKey && typeof quickKey !== "string") quickKey = null; // called from a DOM event
        const txt = this.state.input.trim();
        if (!txt||this.state.loading) return;
        const atts = [...this.state.attachments];
        this.state.input="";
        this.state.attachments=[];
        const attachNames = atts.map(a=>a.name);
        this._push("user", txt+(attachNames.length?`\n📎 ${attachNames.join(", ")}`:""), {attachNames});
        this.state.loading=true;
        const tid=uid();
        const willBeLocal = !!quickKey;
        this.state.msgs.push({id:tid,role:"assistant",status:"typing",html:markup(""),time:ts(),
            loadingText: willBeLocal ? "Fetching from Odoo…" : "Thinking…"});
        // after a moment, tell the user Claude is working (local answers return before this)
        const slowTimer = setTimeout(() => {
            const t = this.state.msgs.find(m => m.id === tid);
            if (t) t.loadingText = "Claude is working on it…";
        }, 1500);
        this._scroll();
        try {
            const res = await rpc("/claude_ai/chat",{
                session_id: this.state.sessionId,
                user_message: txt,
                attachments: atts.map(a=>({filename:a.name,data:a.b64,type:a.type})),
                quick_key: quickKey,
            });
            clearTimeout(slowTimer);
            const idx=this.state.msgs.findIndex(m=>m.id===tid);
            if(idx!==-1) this.state.msgs.splice(idx,1);
            if (res.error) {
                this._push("assistant",`⚠️ ${res.message}`);
            } else {
                this.state.totalTokens=res.total_tokens||0;
                if (res.savings) this.state.savings=res.savings;
                this._push("assistant",res.message,{
                    source:             res.source,
                    tokens_used:        res.tokens_used,
                    refresh_needed:     res.refresh_needed,
                    excel_b64:          res.excel_b64,
                    excel_filename:     res.excel_filename,
                    chart_spec:         res.chart_spec,
                    odoo_op:            res.odoo_operation,
                    op_result:          res.op_result,
                    needs_confirmation: res.needs_confirmation,
                    install_result:     res.install_result,
                    batch_result:       res.batch_result,
                    crud_form:          res.crud_form,
                });
            }
        } catch(e) {
            clearTimeout(slowTimer);
            const idx=this.state.msgs.findIndex(m=>m.id===tid);
            if(idx!==-1) this.state.msgs.splice(idx,1);
            this._push("assistant",`⚠️ ${e.message||e}`);
        } finally { this.state.loading=false; }
    }

    /* ── CRUD handlers ───────────────────────────────── */
    async onQuickCreate(ev) {
        const type = ev.currentTarget.dataset.type;
        const tmpl = QUICK_CREATE_TEMPLATES[type];
        if (!tmpl) return;
        const notif = this.notif;
        openCrudModal(tmpl, async (vals) => {
            const op = {model: tmpl.model, method: "create", args: [vals], kwargs: {}};
            this._push("user", `Create new ${type}: ${JSON.stringify(vals)}`);
            const tid = uid();
            this.state.msgs.push({id:tid, role:"assistant", status:"typing", html:markup(""), time:ts()});
            this._scroll();
            try {
                const r = await rpc("/claude_ai/execute", {operation: op});
                const idx = this.state.msgs.findIndex(m=>m.id===tid);
                if (idx!==-1) this.state.msgs.splice(idx,1);
                if (r.success) {
                    const result = r.result;
                    const name = result.name || `ID ${result.id}`;
                    this._push("assistant", `✅ **${type.charAt(0).toUpperCase()+type.slice(1)} created successfully!**

**${name}** (ID: ${result.id}) has been added to your database.

Would you like to view or edit this record?`, {op_result: result});
                    notif.add("Record created!", {type:"success"});
                } else {
                    this._push("assistant", `❌ **Create failed:** ${r.error}`);
                }
            } catch(e) {
                const idx = this.state.msgs.findIndex(m=>m.id===tid);
                if (idx!==-1) this.state.msgs.splice(idx,1);
                this._push("assistant", `❌ ${e.message||e}`);
            } finally { this.state.loading=false; this._scroll(); }
        });
    }

    onOpenCrudForm(ev) {
        const m = this._getMsgById(ev.currentTarget.dataset.msgid);
        if (!m || !m.crudForm) return;
        const spec = m.crudForm;
        const notif = this.notif;
        openCrudModal(spec, async (vals) => {
            let op;
            if (spec.action === "create") {
                op = {model: spec.model, method: "create", args: [vals], kwargs: {}};
            } else if (spec.action === "write") {
                op = {model: spec.model, method: "write", args: [[spec.id], vals], kwargs: {}};
            } else if (spec.action === "unlink") {
                op = {model: spec.model, method: "unlink", args: [[spec.id]], kwargs: {}};
            }
            if (!op) return;
            this.state.loading = true;
            try {
                const r = await rpc("/claude_ai/execute", {operation: op});
                if (r.success) {
                    let msg = spec.action === "create"
                        ? `✅ Record created successfully (ID: ${r.result?.id})`
                        : spec.action === "write"
                        ? "✅ Record updated successfully"
                        : "✅ Record deleted permanently";
                    this._push("assistant", msg, {op_result: r.result});
                    notif.add(msg.replace("✅ ",""), {type:"success"});
                } else {
                    this._push("assistant", `❌ **Operation failed:** ${r.error}`);
                }
            } catch(e) { this._push("assistant", `❌ ${e.message||e}`); }
            finally { this.state.loading=false; this._scroll(); }
        });
    }

    async clearChat() {
        const r=await rpc("/claude_ai/clear",{session_id:this.state.sessionId});
        if(r.new_session_id) this.state.sessionId=r.new_session_id;
        this.state.msgs=[]; this.state.totalTokens=0; this.state.attachments=[];
        this._boot();
    }

    goConfig() { window.location.href="/odoo/action-claude_ai_odoo.action_claude_config"; }
}

registry.category("actions").add("claude_ai.ChatWidget", ClaudeChatWidget);
