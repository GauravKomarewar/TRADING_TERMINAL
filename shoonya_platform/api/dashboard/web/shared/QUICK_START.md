# ⚡ Adding a New Page — Quick Start

## 3-Step Process

### 1️⃣ Register Page in pages-config.js

```javascript
// Add to ./shared/pages-config.js in the PAGES array:
{
    id: 'my-page',              // ← Unique ID
    label: 'My Page',           // ← Navigation label
    href: '/dashboard/web/my-page.html',
    icon: '🎯'                  // ← Optional emoji
}
```

### 2️⃣ Create HTML File

Copy `./shared/_TEMPLATE.html` to `./my-page.html` and customize:

**Minimum required:**
```html
<head>
    <link rel="stylesheet" href="/dashboard/web/styles/common.css">
    <link rel="stylesheet" href="/dashboard/web/shared/layout.css">
    <script src="/dashboard/web/shared/pages-config.js" defer></script>
    <script src="/dashboard/web/shared/layout.js" defer></script>
</head>

<!-- MUST match pages-config.js id -->
<body data-page="my-page">
    <div id="app-header"></div>
    <main>
        Your content here
    </main>
</body>
```

### 3️⃣ Done! ✅

Navigation automatically updates. No additional config needed.

---

## Key Rules

| Rule | Example |
|------|---------|
| **Config ID must match data-page** | ID: `my-page` → `data-page="my-page"` |
| **Use kebab-case for IDs** | ✅ `my-page` ❌ `myPage` ❌ `my_page` |
| **Load config BEFORE layout.js** | `pages-config.js` first, then `layout.js` |
| **Include app-header div** | `<div id="app-header"></div>` required |
| **Use system font stack** | `-apple-system, BlinkMacSystemFont, 'Segoe UI'...` |

---

## Example: Adding "Analytics" Page

### Step 1: Update pages-config.js
```javascript
{
    id: 'analytics',
    label: 'Analytics',
    href: '/dashboard/web/analytics.html',
    icon: '📊'
}
```

### Step 2: Create analytics.html
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Analytics – Shoonya Platform</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <link rel="stylesheet" href="/dashboard/web/styles/common.css">
    <link rel="stylesheet" href="/dashboard/web/shared/layout.css">
    <script src="/dashboard/web/shared/pages-config.js" defer></script>
    <script src="/dashboard/web/shared/layout.js" defer></script>
</head>

<body data-page="analytics">
    <div id="app-header"></div>
    
    <main>
        <h1>📊 Analytics</h1>
        <p>Your analytics content here...</p>
    </main>
</body>
</html>
```

### Step 3: Verify
- Open any dashboard page
- "Analytics" appears in navigation
- Click it to view the new page

---

## Navigation Auto-Updates For:

- ✅ New pages added to pages-config.js
- ✅ Page label changes
- ✅ Page icon changes
- ✅ All browsers (desktop, tablet, mobile)
- ✅ Without restarting server

---

## Common Mistakes ❌

| Mistake | Problem | Fix |
|---------|---------|-----|
| Forget `<div id="app-header"></div>` | No navigation appears | Add the div before `<main>` |
| Wrong `data-page` ID | Not highlighted as active | Match exactly with pages-config.js `id` |
| Load layout.js before pages-config.js | Config not loaded | Reverse script order |
| Use spaces in page ID | Navigation fails | Use kebab-case: `my-page` |
| CamelCase ID | ID mismatch | Use lowercase: `mypage` or `my-page` |

---

## File Locations

```
/ shared/
  ├─ pages-config.js      ← Edit this to add pages ⭐
  ├─ layout.js            ← Do not edit
  ├─ layout.css           ← Do not edit
  ├─ _TEMPLATE.html       ← Copy for new pages ⭐
  └─ README.md            ← Full documentation

/ web/
  ├─ dashboard.html
  ├─ orderbook.html
  ├─ my-page.html         ← Create new pages here ⭐
  └─ (other pages)
```

---

## Need Help?

1. **See full documentation**: `./shared/README.md`
2. **Copy working example**: `./shared/_TEMPLATE.html`
3. **Reference existing page**: `dashboard.html`, `orderbook.html`

---

**That's it! 🚀 Your page is now live in the navigation.**
