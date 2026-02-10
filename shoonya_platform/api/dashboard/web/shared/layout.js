(function () {
    const body = document.body;
    if (!body) return;

    const pageId = body.dataset.page || 'dashboard';
    body.classList.add('dashboard-shell', `page-${pageId}`);

    const navItems = [
        { id: 'dashboard', label: 'Dashboard', href: '/dashboard/web/dashboard.html' },
        { id: 'option-chain', label: 'Option Chain', href: '/dashboard/web/option_chain_dashboard.html' },
        { id: 'orders', label: 'Orders', href: '/dashboard/web/orderbook.html' },
        { id: 'place-order', label: 'Place Order', href: '/dashboard/web/place_order.html' },
        { id: 'strategy', label: 'Strategy', href: '/dashboard/web/strategy.html' },
        { id: 'diagnostics', label: 'Diagnostics', href: '/dashboard/web/diagnostics.html' }
    ];

    const header = document.createElement('header');
    header.className = 'app-header';

    const brand = document.createElement('div');
    brand.className = 'app-brand';
    brand.textContent = '◬ Shoonya';
    brand.addEventListener('click', () => {
        window.location.href = '/dashboard/web/dashboard.html';
    });

    const mobileToggle = document.createElement('button');
    mobileToggle.className = 'app-mobile-toggle';
    mobileToggle.type = 'button';
    mobileToggle.textContent = '☰';

    const nav = document.createElement('nav');
    nav.className = 'app-nav';

    navItems.forEach((item) => {
        const link = document.createElement('a');
        link.className = 'nav-link';
        link.href = item.href;
        link.textContent = item.label;
        if (item.id === pageId) {
            link.classList.add('active');
        }
        nav.appendChild(link);
    });

    mobileToggle.addEventListener('click', () => {
        nav.classList.toggle('open');
    });

    const actions = document.createElement('div');
    actions.className = 'app-actions';

    const logoutBtn = document.createElement('button');
    logoutBtn.className = 'btn-secondary btn-sm';
    logoutBtn.id = 'appLogout';
    logoutBtn.textContent = 'Logout';
    logoutBtn.addEventListener('click', async () => {
        try {
            await fetch('/auth/logout', { method: 'POST', credentials: 'include' });
        } catch (e) {
            // Ignore logout errors
        }
        window.location.href = '/';
    });

    actions.appendChild(logoutBtn);

    header.appendChild(brand);
    header.appendChild(mobileToggle);
    header.appendChild(nav);
    header.appendChild(actions);

    const mount = document.getElementById('app-header');
    if (mount) {
        mount.appendChild(header);
    } else {
        body.insertBefore(header, body.firstChild);
    }

    // Create global index ticker ribbon at top of page
    const ticker = document.createElement('div');
    ticker.className = 'global-ticker';
    ticker.id = 'globalTicker';
    ticker.innerHTML = `
        <div class="ticker-track" id="tickerTrack">
            <div class="ticker-items" id="tickerItems">
                <!-- Index tokens will be loaded here -->
            </div>
        </div>
    `;
    
    // Insert at very top of body
    body.insertBefore(ticker, body.firstChild);

    // Load and refresh index tokens
    let indexTokensTimer = null;
    
    function loadGlobalIndexTokens() {
        fetch('/dashboard/index-tokens/prices', {credentials:'include'})
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(data => updateGlobalTicker(data.indices || {}, data.subscribed || []))
            .catch(() => {});  // Silently fail if not available
    }
    
    function updateGlobalTicker(indicesData, subscribedList) {
        const itemsContainer = document.getElementById('tickerItems');
        const tickerTrack = document.getElementById('tickerTrack');
        if (!itemsContainer || !tickerTrack) return;
        
        if (!subscribedList.length) {
            document.getElementById('globalTicker').style.display = 'none';
            return;
        }
        
        document.getElementById('globalTicker').style.display = 'block';
        
        // Sort: INDIAVIX first, then NIFTY, BANKNIFTY, SENSEX, then rest alphabetically
        const priority = ['INDIAVIX', 'NIFTY', 'BANKNIFTY', 'SENSEX'];
        const sorted = [
            ...priority.filter(s => subscribedList.includes(s)),
            ...subscribedList.filter(s => !priority.includes(s)).sort()
        ];
        
        let html = '';
        sorted.forEach(symbol => {
            if (indicesData[symbol]) {
                const data = indicesData[symbol];
                const ltp = data.ltp || 0;
                const pc = data.pc || 0;
                const changeClass = pc >= 0 ? 'up' : 'down';
                const arrow = pc >= 0 ? '▲' : '▼';
                
                html += `
                    <div class="ticker-item">
                        <span class="ticker-symbol">${symbol}</span>
                        <span class="ticker-ltp ${changeClass}">₹${ltp.toFixed(2)}</span>
                        <span class="ticker-change ${changeClass}">${arrow} ${Math.abs(pc).toFixed(2)}%</span>
                    </div>
                `;
            }
        });
        
        if (html) {
            itemsContainer.innerHTML = html;
            // Check if animation is needed (items overflow container)
            setTimeout(() => {
                const itemsWidth = itemsContainer.scrollWidth;
                const trackWidth = tickerTrack.clientWidth;
                if (itemsWidth > trackWidth) {
                    itemsContainer.classList.add('animate-scroll');
                } else {
                    itemsContainer.classList.remove('animate-scroll');
                }
            }, 50);
        }
    }
    
    // Start ticker on page load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            loadGlobalIndexTokens();
            indexTokensTimer = setInterval(loadGlobalIndexTokens, 2000);
        });
    } else {
        loadGlobalIndexTokens();
        indexTokensTimer = setInterval(loadGlobalIndexTokens, 2000);
    }
})();
