/** @odoo-module **/
// ═══════════════════════════════════════════════════════════
//  PROX PROFESSIONAL  v7
//  10 themes · Smart buttons preserved · Auto bg/text fix
//  Odoo 19 / OWL — no framework layout interference
// ═══════════════════════════════════════════════════════════

const KEY = 'prox5';

const THEMES = [
  { id:'parchment', name:'Parchment',   desc:'Warm ivory editorial',   s:['#F5F3EE','#0F1117','#2563EB','#C9A84C'] },
  { id:'slate',     name:'Ocean Slate', desc:'Cool navy corporate',    s:['#EDF3FB','#0A1929','#0369A1','#F59E0B'] },
  { id:'forest',    name:'Forest',      desc:'Deep green & earth',     s:['#EBF4EC','#0D1F0F','#15803D','#CA8A04'] },
  { id:'midnight',  name:'Midnight',    desc:'Dark electric indigo',   s:['#090C1A','#111428','#6366F1','#FCD34D'] },
  { id:'rose',      name:'Rose',        desc:'Crimson & blush',        s:['#FEF5F6','#1F0A0D','#BE123C','#D97706'] },
  { id:'obsidian',  name:'Obsidian',    desc:'Charcoal & gold',        s:['#0E1012','#191C20','#C9A84C','#E5C878'] },
  { id:'arctic',    name:'Arctic',      desc:'Ice white & cobalt',     s:['#EDF5FF','#071830','#0050B3','#FA8C16'] },
  { id:'amber',     name:'Amber',       desc:'Honey & espresso',       s:['#FDFAF0','#1A1000','#B45309','#D97706'] },
  { id:'aurora',    name:'Aurora',      desc:'Teal & dark ocean',      s:['#080F14','#0E1A22','#00BCD4','#F06292'] },
  { id:'lavender',  name:'Lavender',    desc:'Soft purple luxury',     s:['#F4F2FA','#1A1030','#6D28D9','#D97706'] },
];

// Accent colours for progress bar (must match SCSS vars)
const ACCENT = {
  parchment:'#2563EB', slate:'#0369A1', forest:'#15803D',
  midnight:'#6366F1',  rose:'#BE123C',  obsidian:'#C9A84C',
  arctic:'#0050B3',    amber:'#B45309', aurora:'#00BCD4', lavender:'#6D28D9',
};
const GOLD = {
  parchment:'#C9A84C', slate:'#F59E0B', forest:'#CA8A04',
  midnight:'#FCD34D',  rose:'#D97706',  obsidian:'#E5C878',
  arctic:'#FA8C16',    amber:'#D97706', aurora:'#F06292',  lavender:'#D97706',
};

// ── Apply theme before paint to avoid flash ──────────────
(function(){
  const t = localStorage.getItem(KEY) || 'parchment';
  document.documentElement.setAttribute('data-prox-theme', t);
})();

// ── DOM Ready ─────────────────────────────────────────────
function boot() {

  // ── Progress bar ──────────────────────────────────────
  if (!document.getElementById('prox-bar')) {
    const bar = document.createElement('div');
    bar.id = 'prox-bar';
    const t = document.documentElement.getAttribute('data-prox-theme')||'parchment';
    Object.assign(bar.style, {
      position:'fixed', top:'0', left:'0', right:'0',
      height:'2px', zIndex:'99999', pointerEvents:'none',
      opacity:'0', width:'0%',
      background:`linear-gradient(90deg,${ACCENT[t]} 0%,${GOLD[t]} 55%,${ACCENT[t]} 100%)`,
      transition:'width .14s ease, opacity .26s ease',
    });
    document.body.appendChild(bar);

    let _tid;
    const go = () => {
      clearTimeout(_tid); bar.style.opacity = '1';
      let w = 0; bar.style.width = '0%';
      const tick = () => {
        w = w < 70 ? w + Math.random()*12 : w + .6;
        if (w > 91) w = 91;
        bar.style.width = w + '%';
        _tid = setTimeout(tick, 130 + Math.random()*80);
      };
      _tid = setTimeout(tick, 20);
    };
    const end = () => {
      clearTimeout(_tid); bar.style.width = '100%';
      setTimeout(() => { bar.style.opacity = '0'; setTimeout(()=>bar.style.width='0%', 320); }, 150);
    };
    const orig = window.fetch;
    window.fetch = function(...a){ go(); return orig.apply(this,a).finally(end); };
  }

  // ── Theme panel ────────────────────────────────────────
  if (!document.getElementById('prox-fab')) buildPanel();

  // ── Ctrl+/ → search ───────────────────────────────────
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey||e.metaKey) && e.key==='/') {
      e.preventDefault();
      const el = document.querySelector('.o_searchview input, .o_cp_searchview input');
      if (el) { el.focus(); el.select(); }
    }
  });

  // ── Fix dark stray backgrounds (graph/pivot) ──────────
  fixBg();

  // ── Staggered list rows ────────────────────────────────
  animRows();

  // ── Watch DOM ─────────────────────────────────────────
  new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) {
      if (n.nodeType !== 1) continue;
      if (n.classList?.contains('o_list_view') || n.querySelector?.('.o_list_view'))
        setTimeout(animRows, 50);
      if (n.classList?.contains('o_graph_view') || n.classList?.contains('o_pivot_view') ||
          n.querySelector?.('.o_graph_view,.o_pivot_view') || n.tagName==='CANVAS')
        setTimeout(fixBg, 90);
    }
  }).observe(document.body, { childList:true, subtree:true });
}

// ── Build theme switcher panel ─────────────────────────────
function buildPanel() {
  const cur = localStorage.getItem(KEY) || 'parchment';

  // FAB
  const fab = document.createElement('button');
  fab.id = 'prox-fab';
  fab.title = 'Switch theme — Prox Professional';
  fab.setAttribute('aria-label', 'Switch theme');
  fab.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/>
    <circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/>
    <circle cx="8.5"  cy="7.5"  r=".5" fill="currentColor"/>
    <circle cx="6.5"  cy="12.5" r=".5" fill="currentColor"/>
    <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.059 0-.926.771-1.688 1.688-1.688h1.977c3.026 0 5.562-2.537 5.562-5.563C22 6.5 17.5 2 12 2z"/>
  </svg>`;
  document.body.appendChild(fab);

  // Panel drawer
  const panel = document.createElement('div');
  panel.id = 'prox-panel';

  const hdr = document.createElement('div');
  hdr.id = 'prox-panel-hdr';
  hdr.textContent = 'Interface Theme';
  panel.appendChild(hdr);

  THEMES.forEach(theme => {
    const opt = document.createElement('div');
    opt.className = 'prox-opt' + (theme.id === cur ? ' on' : '');

    // 2×2 swatch
    const sw = document.createElement('div');
    sw.className = 'prox-sw';
    theme.s.forEach(c => { const s = document.createElement('s'); s.style.background = c; sw.appendChild(s); });

    // Labels
    const lbl = document.createElement('div');
    lbl.className = 'prox-lbl';
    lbl.innerHTML = `<span class="prox-name">${theme.name}</span><span class="prox-desc">${theme.desc}</span>`;

    // Checkmark
    const chk = document.createElement('span');
    chk.className = 'prox-chk'; chk.textContent = '✓';

    opt.append(sw, lbl, chk);
    panel.appendChild(opt);

    opt.addEventListener('click', () => {
      document.querySelectorAll('.prox-opt').forEach(o => o.classList.remove('on'));
      opt.classList.add('on');
      document.documentElement.setAttribute('data-prox-theme', theme.id);
      localStorage.setItem(KEY, theme.id);

      // Update progress bar gradient
      const bar = document.getElementById('prox-bar');
      if (bar) bar.style.background =
        `linear-gradient(90deg,${ACCENT[theme.id]} 0%,${GOLD[theme.id]} 55%,${ACCENT[theme.id]} 100%)`;

      // Re-fix any stray dark containers
      setTimeout(fixBg, 60);
    });
  });

  document.body.appendChild(panel);

  // Toggle
  fab.addEventListener('click', e => { e.stopPropagation(); panel.classList.toggle('open'); });
  document.addEventListener('click', e => { if (!panel.contains(e.target) && e.target !== fab) panel.classList.remove('open'); });
}

// ── Fix stray dark backgrounds (graph/pivot containers) ────
// FIX v7: Scope ONLY to graph/pivot renderer divs — NOT o_view_controller
// Setting inline styles on o_view_controller was blocking button clicks
// in analytical views because the stacking context was broken.
function fixBg() {
  const t = document.documentElement.getAttribute('data-prox-theme') || 'parchment';
  const isDark = ['midnight','obsidian','aurora'].includes(t);

  const cs = getComputedStyle(document.documentElement);
  const bg   = cs.getPropertyValue('--c-bg').trim()   || '#F5F3EE';
  const card = cs.getPropertyValue('--c-card').trim() || '#FFFFFF';
  const ink  = cs.getPropertyValue('--c-t1').trim()   || '#141210';

  // IMPORTANT: Do NOT include .o_view_controller here — inline styles on it
  // break z-index/stacking and block button pointer events in pivot/graph views.
  // Only target the inner renderer divs which may get Odoo's default dark fill.
  document.querySelectorAll(
    '.o_graph_renderer, .o_graph_view > .o_content,' +
    '.o_pivot_renderer, .o_pivot_view > .o_content'
  ).forEach(el => {
    const rgb = getComputedStyle(el).backgroundColor.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!rgb) return;
    const bright = (+rgb[1] + +rgb[2] + +rgb[3]) / 3;
    if (bright < 20 && !isDark) {
      el.style.setProperty('background-color', bg, 'important');
      el.style.setProperty('color', ink, 'important');
    }
  });

  // Canvas always gets theme card color
  document.querySelectorAll('.o_graph_view canvas, .o_graph_renderer canvas').forEach(c => {
    c.style.background = card;
  });
}

// ── Staggered list row entrance ────────────────────────────
function animRows() {
  const tbody = document.querySelector('.o_list_view tbody');
  if (!tbody) return;
  const rows = tbody.querySelectorAll('tr:not(.pi)');
  if (!rows.length) return;
  rows.forEach((row, i) => {
    row.classList.add('pi');
    row.style.cssText += ';opacity:0;transform:translateY(5px);' +
      `transition:opacity 170ms ease ${i*20}ms,transform 170ms ease ${i*20}ms`;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      row.style.opacity = '1'; row.style.transform = 'translateY(0)';
    }));
  });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
