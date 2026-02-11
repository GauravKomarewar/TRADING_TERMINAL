# 📱 Shared Layout System — Documentation

## Overview

The shared layout system provides **automatic navigation updates** across all dashboard pages. When you add a new page to the web folder, it automatically appears in the navigation menu without requiring code changes.

## Architecture

```
web/
├── shared/
│   ├── layout.css              ← Common styles (ticker, nav bar)
│   ├── layout.js               ← Loads nav from pages-config.js
│   ├── pages-config.js         ← Configuration for all pages
│   ├── _TEMPLATE.html          ← Template for new pages
│   └── README.md               ← This file
│
├── styles/
│   └── common.css              ← Base styles for all pages
│
├── dashboard.html              ← Updated to use shared config
├── orderbook.html              ← Updated to use shared config
├── option_chain_dashboard.html ← Updated to use shared config
├── place_order.html            ← Updated to use shared config
├── strategy.html               ← Updated to use shared config
└── diagnostics.html            ← Updated to use shared config
```

## How It Works

### 1. **Pages Configuration** (`pages-config.js`)
Central registry of all dashboard pages:

```javascript
const PAGES = [
    {
        id: 'dashboard',
        label: 'Dashboard',
        href: '/dashboard/web/dashboard.html',
        icon: '📊'
    },
    {
        id: 'orders',
        label: 'Orders',
        href: '/dashboard/web/orderbook.html',
        icon: '⚡'
    },
    // Add more pages here...
];
```

### 2. **Layout Script** (`layout.js`)
Automatically loads navigation from `pages-config.js`:

```javascript
// If pages-config.js is loaded, use its configuration
if (typeof getNavItems === 'function') {
    NAV_ITEMS = getNavItems();
}
```

### 3. **Page Structure**
All pages follow the same structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <!-- Load shared config BEFORE layout.js -->
    <script src="/dashboard/web/shared/pages-config.js" defer></script>
    <script src="/dashboard/web/shared/layout.js" defer></script>
</head>

<!-- IMPORTANT: data-page must match ID from pages-config.js -->
<body data-page="page-id">
    <!-- Navigation is injected here -->
    <div id="app-header"></div>
    
    <main>
        <!-- Your content -->
    </main>
</body>
</html>
```

## Adding a New Page

### Step 1: Register the Page
Edit `shared/pages-config.js` and add to the `PAGES` array:

```javascript
{
    id: 'my-page',           // Unique ID (kebab-case, no spaces)
    label: 'My Page',        // Display name in navigation
    href: '/dashboard/web/my-page.html',
    icon: '✨'               // Optional emoji
}
```

### Step 2: Create the HTML File
Copy the template from `shared/_TEMPLATE.html` and customize:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>My Page – Shoonya Platform</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <link rel="stylesheet" href="/dashboard/web/styles/common.css">
    <link rel="stylesheet" href="/dashboard/web/shared/layout.css">
    <script src="/dashboard/web/shared/pages-config.js" defer></script>
    <script src="/dashboard/web/shared/layout.js" defer></script>
    
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
        }
    </style>
</head>

<!-- IMPORTANT: data-page attribute must match ID from pages-config.js -->
<body data-page="my-page">
    <div id="app-header"></div>
    
    <main>
        <h1>My Page Title</h1>
        <!-- Your content here -->
    </main>
    
    <script>
        // Your page logic
        window.addEventListener('DOMContentLoaded', function() {
            console.log('Page loaded!');
        });
    </script>
</body>
</html>
```

### Step 3: Done!
That's it! The page automatically appears in the navigation menu.

## Features Included

- ✅ **Ticker Ribbon** — Auto-refreshing market data at top
- ✅ **Navigation Bar** — Auto-populated from configuration
- ✅ **Hamburger Menu** — Mobile responsive, auto-hides/shows
- ✅ **Active Link Highlight** — Current page highlighted in nav
- ✅ **Logout Button** — Auto-injected in header
- ✅ **Responsive Design** — Works on all screen sizes

## Customization

### Change Active Page Style
Edit `layout.css` to customize the `.nav-link.active` style.

### Add Page Icons
Any emoji or symbol can be used as `icon` in pages-config.js (currently not displayed, but ready for UI expansion).

### Change Navigation Appearance
Modify styles in `layout.css`:
- `.app-header` — Navigation bar styling
- `.nav-link` — Navigation link styling
- `.hamburger-btn` — Mobile menu button

### Auto-detect Pages (Server-side Enhancement)
To make pages auto-discovered from filesystem (advanced):

1. Create a backend endpoint:
```python
@app.get("/dashboard/web/api/pages")
def list_available_pages():
    # Scan web/ folder for .html files
    # Return page metadata
    return {"pages": [...]}
```

2. Update `layout.js` to fetch:
```javascript
async function loadPages() {
    const res = await fetch('/dashboard/web/api/pages');
    const data = await res.json();
    NAV_ITEMS = data.pages;
}
```

## Font Consistency

All pages use the **system font stack**:
```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
```

This ensures consistency with the **ticker ribbon** and provides optimal font rendering across platforms.

## Mobile Responsiveness

The layout automatically handles:
- **Desktop** — Full horizontal navigation
- **Tablet** (≤1024px) — Condensed navigation
- **Mobile** (≤768px) — Hamburger menu with slide-down panel
- **Small Mobile** (≤480px) — Further optimizations

## Troubleshooting

### Navigation Not Appearing
1. ✅ Verify `<div id="app-header"></div>` is in your HTML
2. ✅ Verify `data-page` attribute matches pages-config.js ID
3. ✅ Verify pages-config.js loads BEFORE layout.js

### Current Page Not Highlighted
1. ✅ Check `data-page` attribute exactly matches pages-config.js `id`
2. ✅ Clear browser cache

### Page Not Appearing in Navigation
1. ✅ Verify page is registered in pages-config.js `PAGES` array
2. ✅ Verify page ID matches between config and `data-page` attribute
3. ✅ Hard refresh browser (Ctrl+Shift+R)

## File Reference

| File | Purpose |
|------|---------|
| `pages-config.js` | Central page registry — edit this to add pages |
| `layout.js` | Navigation + ticker ribbon logic |
| `layout.css` | Shared styles for nav + ticker |
| `_TEMPLATE.html` | Copy this for new pages |
| `common.css` | Base styles for all pages |

## Next Steps

1. ✅ To add a new page: Edit `pages-config.js`
2. ✅ Create HTML file using `_TEMPLATE.html`
3. ✅ Navigation auto-updates!

---

**Questions?** Check existing pages (dashboard.html, orderbook.html) for examples.
