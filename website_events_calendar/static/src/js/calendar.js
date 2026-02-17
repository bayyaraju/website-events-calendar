/** @odoo-module **/
/**
 * Website Events Calendar - Professional UI
 * Loads Google Fonts + FullCalendar 6 from CDN at runtime.
 * No @import in CSS, no template inheritance of web.layout.
 */

(function () {
    'use strict';

    function loadScript(src, cb) {
        var s = document.createElement('script');
        s.src = src;
        s.onload = cb;
        s.onerror = function () { console.error('WEC: failed to load', src); };
        document.head.appendChild(s);
    }

    function loadCSS(href) {
        var l = document.createElement('link');
        l.rel = 'stylesheet';
        l.href = href;
        document.head.appendChild(l);
    }

    /* ------------------------------------------------------------------ */
    /*  Inject Google Fonts safely via JS (avoids CSS @import issue)        */
    /* ------------------------------------------------------------------ */
    function loadGoogleFonts() {
        // Only load on the calendar page
        if (!document.getElementById('wec-calendar')) return;
        loadCSS('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&display=swap');
    }

    /* ------------------------------------------------------------------ */
    /*  Utility                                                              */
    /* ------------------------------------------------------------------ */
    function formatDateRange(startStr, endStr) {
        if (!startStr) return '';
        var dateOpts = { month: 'short', day: 'numeric', year: 'numeric' };
        var timeOpts = { hour: '2-digit', minute: '2-digit' };
        try {
            var s = new Date(startStr);
            var e = endStr ? new Date(endStr) : null;
            var sd = s.toLocaleDateString(undefined, dateOpts);
            var st = s.toLocaleTimeString(undefined, timeOpts);
            if (!e) return sd + ' · ' + st;
            var ed = e.toLocaleDateString(undefined, dateOpts);
            var et = e.toLocaleTimeString(undefined, timeOpts);
            if (sd === ed) return sd + '  ·  ' + st + ' – ' + et;
            return sd + '  →  ' + ed;
        } catch (err) { return startStr; }
    }

    /* ------------------------------------------------------------------ */
    /*  Tooltip                                                              */
    /* ------------------------------------------------------------------ */
    var tipTimer = null;

    function getTip() { return document.getElementById('wec-tooltip'); }

    function showTip(info, mx, my) {
        clearTimeout(tipTimer);
        var t = getTip();
        if (!t) return;
        var ev    = info.event;
        var props = ev.extendedProps || {};
        var color = ev.backgroundColor || ev.color || '#c8f564';

        var bar = document.getElementById('wec-tooltip-colorbar');
        if (bar) bar.style.background = color;

        document.getElementById('wec-tooltip-title').textContent = ev.title || 'Event';

        var badgeEl = document.getElementById('wec-tooltip-type');
        var typeName = props.event_type || props.type || '';
        if (typeName) { badgeEl.textContent = typeName; badgeEl.style.display = ''; }
        else { badgeEl.style.display = 'none'; }

        document.getElementById('wec-tooltip-date').textContent = formatDateRange(
            ev.startStr || (ev.start ? ev.start.toISOString() : ''),
            ev.endStr   || (ev.end   ? ev.end.toISOString()   : '')
        );

        var locRow = document.getElementById('wec-tooltip-loc-row');
        var locEl  = document.getElementById('wec-tooltip-loc');
        if (props.location) { locEl.textContent = props.location; locRow.style.display = ''; }
        else { locRow.style.display = 'none'; }

        var seatsRow = document.getElementById('wec-tooltip-seats-row');
        var seatsEl  = document.getElementById('wec-tooltip-seats');
        if (props.seats !== undefined && props.seats >= 0) {
            seatsEl.textContent = props.seats + ' seats available';
            seatsRow.style.display = '';
        } else { seatsRow.style.display = 'none'; }

        t.style.display = 'block';
        posTip(t, mx, my);
    }

    function posTip(t, mx, my) {
        var m = 16, tw = t.offsetWidth || 270, th = t.offsetHeight || 160;
        var vw = window.innerWidth, vh = window.innerHeight;
        var x = mx + m, y = my + m;
        if (x + tw > vw - m) x = mx - tw - m;
        if (y + th > vh - m) y = my - th - m;
        if (x < m) x = m;
        if (y < m) y = m;
        t.style.left = x + 'px';
        t.style.top  = y + 'px';
    }

    function hideTip() {
        var t = getTip();
        if (t) t.style.display = 'none';
    }

    /* ------------------------------------------------------------------ */
    /*  Calendar Init                                                        */
    /* ------------------------------------------------------------------ */
    function initCalendar() {
        var calEl = document.getElementById('wec-calendar');
        if (!calEl) return;

        var allEvents = [];
        try {
            var raw = calEl.getAttribute('data-events');
            if (raw) allEvents = JSON.parse(raw);
        } catch (e) {
            console.error('WEC: cannot parse events JSON', e);
        }

        if (!window.FullCalendar) {
            calEl.innerHTML = '<div class="wec-loading"><div class="wec-spinner"></div><span>Calendar could not be loaded</span></div>';
            return;
        }

        var calendar = new FullCalendar.Calendar(calEl, {
            initialView: 'dayGridMonth',
            headerToolbar: {
                left:   'prev,next today',
                center: 'title',
                right:  ''
            },
            events:     allEvents,
            editable:   false,
            selectable: false,
            dayMaxEvents: 4,
            height: 'auto',
            expandRows: true,
            eventTimeFormat: { hour: '2-digit', minute: '2-digit', meridiem: 'short' },

            eventMouseEnter: function (info) {
                var rect = info.el.getBoundingClientRect();
                showTip(info, rect.left + rect.width / 2, rect.bottom);
                info.el._wecMM = function (e) { posTip(getTip(), e.clientX, e.clientY); };
                info.el.addEventListener('mousemove', info.el._wecMM);
            },

            eventMouseLeave: function (info) {
                if (info.el._wecMM) {
                    info.el.removeEventListener('mousemove', info.el._wecMM);
                    delete info.el._wecMM;
                }
                tipTimer = setTimeout(hideTip, 120);
            },

            eventClick: function (info) {
                info.jsEvent.preventDefault();
                hideTip();
                if (info.event.url) window.location.href = info.event.url;
            }
        });

        calendar.render();

        document.addEventListener('click', function (e) {
            if (!e.target.closest('.fc-event')) hideTip();
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') hideTip();
        });

        document.querySelectorAll('.wec-view-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                document.querySelectorAll('.wec-view-btn').forEach(function (b) {
                    b.classList.remove('active');
                });
                this.classList.add('active');
                if (this.dataset.view) {
                    calendar.changeView(this.dataset.view);
                    hideTip();
                }
            });
        });
    }

    /* ------------------------------------------------------------------ */
    /*  Bootstrap                                                            */
    /* ------------------------------------------------------------------ */
    function onReady(fn) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', fn);
        } else {
            fn();
        }
    }

    onReady(function () {
        if (!document.getElementById('wec-calendar')) return;

        loadGoogleFonts();
        loadCSS('https://cdn.jsdelivr.net/npm/fullcalendar@6.1.10/index.global.min.css');
        loadScript(
            'https://cdn.jsdelivr.net/npm/fullcalendar@6.1.10/index.global.min.js',
            function () { initCalendar(); }
        );
    });

})();
