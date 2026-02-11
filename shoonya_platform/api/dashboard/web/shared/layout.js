/* ================================================================
   Shared Layout — Nav Bar + Ticker Ribbon (all dashboard pages)
   ================================================================ */
(function () {
    'use strict';

    const body = document.body;
    if (!body) return;

    const pageId = body.dataset.page || 'dashboard';
    body.classList.add('dashboard-shell', `page-${pageId}`);

    /* ── Navigation Configuration (Auto-discovered from pages-config.js) ── */
    // NAV_ITEMS will be populated from pages-config.js if available
    // Fallback to defaults if config not loaded
    let NAV_ITEMS = [
        { id: 'dashboard',    label: 'Dashboard',    href: '/dashboard/web/dashboard.html' },
        { id: 'option-chain', label: 'Option Chain',  href: '/dashboard/web/option_chain_dashboard.html' },
        { id: 'orders',       label: 'Orders',        href: '/dashboard/web/orderbook.html' },
        { id: 'place-order',  label: 'Place Order',   href: '/dashboard/web/place_order.html' },
        { id: 'strategy',     label: 'Strategy',      href: '/dashboard/web/strategy.html' },
        { id: 'diagnostics',  label: 'Diagnostics',   href: '/dashboard/web/diagnostics.html' },
    ];

    // Check if pages-config.js is loaded and use it
    if (typeof getNavItems === 'function') {
        NAV_ITEMS = getNavItems();
    }

    /* Ticker — all symbols scroll continuously like stock exchange ticker */
    const ALL_SYMBOLS = ['INDIAVIX', 'NIFTY', 'SENSEX', 'BANKNIFTY', 'GOLDPETAL', 'SILVERMIC', 'NATGASMINI', 'CRUDEOILM', 'FINNIFTY'];

    /* Full display names */
    const DISPLAY_NAMES = {
        INDIAVIX:    'INDIA VIX',
        NIFTY:       'NIFTY 50',
        SENSEX:      'SENSEX',
        BANKNIFTY:   'BANK NIFTY',
        GOLDPETAL:   'GOLD PETAL',
        SILVERMIC:   'SILVER MIC',
        NATGASMINI:  'NAT GAS MINI',
        CRUDEOILM:   'CRUDE OIL',
        FINNIFTY:    'FIN NIFTY',
    };

    /* ────────────────────────────────────────────────────
       BUILD: Ticker Ribbon — Continuous marquee (top of page)
       ──────────────────────────────────────────────────── */
    const ticker = document.createElement('div');
    ticker.className = 'global-ticker';
    ticker.id = 'globalTicker';

    // Single marquee track — contains TWO identical copies for seamless loop
    const marqueeTrack = document.createElement('div');
    marqueeTrack.className = 'ticker-marquee-track';
    marqueeTrack.id = 'tickerMarqueeTrack';

    // Build chip HTML for one copy of all symbols
    function buildChipPlaceholder(symbol, copyIdx) {
        const name = DISPLAY_NAMES[symbol] || symbol;
        return `<div class="ticker-chip" data-symbol="${symbol}" data-copy="${copyIdx}">` +
            `<span class="ticker-sym">${name}</span>` +
            `<span class="ticker-ltp" style="color:rgba(255,255,255,0.3)">--</span>` +
            `<span class="ticker-pct" style="color:rgba(255,255,255,0.2)">—</span>` +
            `</div><span class="ticker-sep">•</span>`;
    }

    // Two copies for seamless marquee loop
    let copyHTML = '';
    for (let c = 0; c < 2; c++) {
        ALL_SYMBOLS.forEach(s => { copyHTML += buildChipPlaceholder(s, c); });
    }
    marqueeTrack.innerHTML = copyHTML;

    ticker.appendChild(marqueeTrack);
    body.insertBefore(ticker, body.firstChild);

    /* ────────────────────────────────────────────────────
       BUILD: Navigation Bar
       ──────────────────────────────────────────────────── */
    const header = document.createElement('header');
    header.className = 'app-header';

    // Brand (SVG trading logo — candlestick chart icon)
    const brand = document.createElement('div');
    brand.className = 'app-brand';
    brand.innerHTML = `<svg viewBox="0 0 32 32" width="30" height="30" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="4" y="10" width="3" height="12" rx="1" fill="currentColor" opacity="0.4"/>
        <rect x="4" y="6" width="3" height="20" rx="0.5" stroke="currentColor" stroke-width="0" fill="currentColor" opacity="0.2"/>
        <line x1="5.5" y1="4" x2="5.5" y2="28" stroke="currentColor" stroke-width="1.2" opacity="0.3"/>
        <rect x="10" y="7" width="3" height="14" rx="1" fill="currentColor" opacity="0.5"/>
        <line x1="11.5" y1="3" x2="11.5" y2="26" stroke="currentColor" stroke-width="1.2" opacity="0.35"/>
        <rect x="16" y="12" width="3" height="10" rx="1" fill="#22c55e" opacity="0.7"/>
        <line x1="17.5" y1="8" x2="17.5" y2="26" stroke="#22c55e" stroke-width="1.2" opacity="0.5"/>
        <rect x="22" y="5" width="3" height="16" rx="1" fill="#22c55e"/>
        <line x1="23.5" y1="2" x2="23.5" y2="25" stroke="#22c55e" stroke-width="1.2" opacity="0.6"/>
        <path d="M3 24 L8 18 L14 21 L20 12 L28 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.7" fill="none"/>
        <circle cx="28" cy="6" r="2" fill="currentColor"/>
    </svg>`;
    brand.title = 'Shoonya Trading Platform';
    brand.addEventListener('click', () => { window.location.href = '/dashboard/web/dashboard.html'; });

    // Hamburger button (mobile)
    const hamburger = document.createElement('button');
    hamburger.className = 'hamburger-btn';
    hamburger.type = 'button';
    hamburger.setAttribute('aria-label', 'Toggle navigation');
    hamburger.innerHTML = `<div class="hamburger-icon"><span></span><span></span><span></span></div>`;

    // Nav
    const nav = document.createElement('nav');
    nav.className = 'app-nav';
    nav.id = 'appNav';

    NAV_ITEMS.forEach(item => {
        const a = document.createElement('a');
        a.className = 'nav-link';
        a.href = item.href;
        a.textContent = item.label;
        if (item.id === pageId) a.classList.add('active');
        nav.appendChild(a);
    });

    // Overlay (mobile backdrop)
    const overlay = document.createElement('div');
    overlay.className = 'nav-overlay';
    overlay.id = 'navOverlay';

    // Logout
    const actions = document.createElement('div');
    actions.className = 'app-actions';
    const logoutBtn = document.createElement('button');
    logoutBtn.className = 'logout-btn';
    logoutBtn.textContent = 'Logout';
    logoutBtn.addEventListener('click', async () => {
        try { await fetch('/auth/logout', { method: 'POST', credentials: 'include' }); } catch (e) {}
        window.location.href = '/';
    });
    actions.appendChild(logoutBtn);

    // Hamburger toggle
    function toggleMobileNav() {
        const isOpen = nav.classList.toggle('open');
        hamburger.classList.toggle('open', isOpen);
        overlay.classList.toggle('show', isOpen);
        // Prevent body scroll when menu open
        body.style.overflow = isOpen ? 'hidden' : '';
    }

    function closeMobileNav() {
        nav.classList.remove('open');
        hamburger.classList.remove('open');
        overlay.classList.remove('show');
        body.style.overflow = '';
    }

    hamburger.addEventListener('click', toggleMobileNav);
    overlay.addEventListener('click', closeMobileNav);

    // Close on nav link click (mobile)
    nav.addEventListener('click', e => {
        if (e.target.classList.contains('nav-link')) closeMobileNav();
    });

    // Close on Escape
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeMobileNav();
    });

    // Assemble header
    header.appendChild(brand);
    header.appendChild(hamburger);
    header.appendChild(nav);
    header.appendChild(actions);

    // Mount
    const mount = document.getElementById('app-header');
    if (mount) {
        mount.appendChild(header);
        mount.parentNode.insertBefore(overlay, mount.nextSibling);
    } else {
        body.insertBefore(header, ticker.nextSibling);
        body.insertBefore(overlay, header.nextSibling);
    }

    /* ────────────────────────────────────────────────────
       TICKER: Data & Rendering (Marquee)
       ──────────────────────────────────────────────────── */
    let tickerData = {};   // symbol → { ltp, pc }

    // Update all chip instances for a given symbol (both copies)
    function updateChip(symbol, data) {
        const chips = document.querySelectorAll(`.ticker-chip[data-symbol="${symbol}"]`);
        if (!chips.length) return;

        const ltp = data && data.ltp != null ? data.ltp : null;
        const pc  = data && data.pc  != null ? data.pc  : null;

        chips.forEach(chip => {
            const ltpEl = chip.querySelector('.ticker-ltp');
            const pctEl = chip.querySelector('.ticker-pct');

            if (ltp == null) {
                ltpEl.textContent = '--';
                ltpEl.className = 'ticker-ltp';
                ltpEl.style.color = 'rgba(255,255,255,0.3)';
                pctEl.textContent = '—';
                pctEl.className = 'ticker-pct';
                pctEl.style.color = 'rgba(255,255,255,0.2)';
                return;
            }

            const cls = pc >= 0 ? 'up' : 'down';
            const arrow = pc >= 0 ? '▲' : '▼';
            const ltpStr = ltp >= 1000 ? ltp.toLocaleString('en-IN', {maximumFractionDigits:2}) : ltp.toFixed(2);
            const pctStr = Math.abs(pc).toFixed(2);

            ltpEl.textContent = ltpStr;
            ltpEl.className = 'ticker-ltp ' + cls;
            ltpEl.style.color = '';

            pctEl.textContent = `${arrow} ${pctStr}%`;
            pctEl.className = 'ticker-pct ' + cls;
            pctEl.style.color = '';
        });
    }

    /* ── Fetch prices ── */
    function fetchTickerPrices() {
        const query = ALL_SYMBOLS.join(',');
        fetch(`/dashboard/index-tokens/prices?symbols=${query}`, { credentials: 'include' })
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(data => {
                const indices = data.indices || {};
                ALL_SYMBOLS.forEach(s => {
                    if (indices[s]) {
                        tickerData[s] = indices[s];
                        updateChip(s, indices[s]);
                    }
                });
            })
            .catch(() => {}); // fail silently
    }

    /* ── Responsive: close mobile nav on resize ── */
    let resizeDebounce = null;
    window.addEventListener('resize', () => {
        clearTimeout(resizeDebounce);
        resizeDebounce = setTimeout(() => {
            closeMobileNav();
        }, 200);
    });

    /* ── Initialize ── */
    function initTicker() {
        fetchTickerPrices();
        setInterval(fetchTickerPrices, 2000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTicker);
    } else {
        initTicker();
    }

})();
