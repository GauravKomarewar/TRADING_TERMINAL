/* ================================================================
   PAGES CONFIGURATION — Central registry for all dashboard pages
   ================================================================
   
   HOW TO ADD A NEW PAGE:
   1. Add a new entry to PAGES array below with:
      - id: unique identifier (no spaces, use kebab-case)
      - label: display name in navigation
      - href: path to the HTML file
      - icon: optional emoji or symbol
      
   2. Create your HTML file in the web/ folder
   3. Add the standard structure (see PAGE_TEMPLATE below)
   4. Add: <div id="app-header"></div> and <body data-page="{id}">
   5. Navigation updates automatically!
   
   ================================================================ */

const PAGES = [
    {
        id: 'dashboard',
        label: 'Dashboard',
        href: '/dashboard/web/dashboard.html',
        icon: '📊'
    },
    {
        id: 'option-chain',
        label: 'Option Chain',
        href: '/dashboard/web/option_chain_dashboard.html',
        icon: '📈'
    },
    {
        id: 'orders',
        label: 'Orders',
        href: '/dashboard/web/orderbook.html',
        icon: '⚡'
    },
    {
        id: 'place-order',
        label: 'Place Order',
        href: '/dashboard/web/place_order.html',
        icon: '✍️'
    },
    {
        id: 'strategy',
        label: 'Strategy',
        href: '/dashboard/web/strategy.html',
        icon: '⚙️'
    },
    {
        id: 'diagnostics',
        label: 'Diagnostics',
        href: '/dashboard/web/diagnostics.html',
        icon: '🔍'
    }
    // Add more pages here as needed!
];

/* ================================================================
   UTILITY: Get all pages
   ================================================================ */
function getAllPages() {
    return PAGES;
}

/* ================================================================
   UTILITY: Get page by ID
   ================================================================ */
function getPageById(id) {
    return PAGES.find(p => p.id === id);
}

/* ================================================================
   UTILITY: Get navigation items (excludes disabled pages)
   ================================================================ */
function getNavItems() {
    return PAGES.filter(p => p.enabled !== false);
}

/*
   PAGE TEMPLATE - See ./README.md for complete HTML template structure
   (Template stored separately to avoid syntax errors in JavaScript file)
*/
