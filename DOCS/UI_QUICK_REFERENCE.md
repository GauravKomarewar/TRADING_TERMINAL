# Dashboard UI Quick Reference

## 🎨 Using the New Design System

### Import Common CSS
```html
<link rel="stylesheet" href="/web/styles/common.css">
```

### Unified Navigation Template
```html
<header>
    <div class="brand" onclick="window.location.href='/web/dashboard.html'">◬ Shoonya</div>
    <button class="mobile-menu-toggle" onclick="toggleMobileNav()">☰</button>
    <nav class="nav-links" id="navLinks">
        <a href="/web/dashboard.html" class="nav-link">Dashboard</a>
        <a href="/web/option_chain_dashboard.html" class="nav-link">Option Chain</a>
        <a href="/web/orderbook.html" class="nav-link">Orders</a>
        <a href="/web/place_order.html" class="nav-link">Place Order</a>
        <a href="/web/strategy.html" class="nav-link">Strategy</a>
        <a href="/web/diagnostics.html" class="nav-link">Diagnostics</a>
    </nav>
</header>

<script>
function toggleMobileNav() {
    document.getElementById('navLinks').classList.toggle('mobile-open');
}
</script>
```

## 📊 CSS Classes Quick Reference

### Layout
```css
.container          /* Max-width container with padding */
.page-header        /* Page title section */
.main              /* Main content area */
```

### Grid System
```css
.grid              /* Base grid */
.grid-cols-1       /* 1 column */
.grid-cols-2       /* 2 columns */
.grid-cols-3       /* 3 columns */
.grid-cols-4       /* 4 columns (responsive) */
.row               /* Auto-fit grid (min 250px) */
```

### Cards
```css
.card              /* Card container */
.card-header       /* Card header section */
.card-title        /* Card title */
.card-body         /* Card content */
.card-footer       /* Card footer */
```

### Forms
```css
.field             /* Form field wrapper */
label              /* Form label */
input, select, textarea  /* Form inputs */
```

### Buttons
```css
button             /* Base button */
.btn-primary       /* Primary action button */
.btn-success       /* Success button */
.btn-danger        /* Danger/delete button */
.btn-warning       /* Warning button */
.btn-secondary     /* Secondary button */
.btn-sm            /* Small button */
.btn-lg            /* Large button */
```

### Status & Alerts
```css
.badge             /* Inline badge */
.badge-primary     /* Primary badge */
.badge-success     /* Success badge */
.badge-danger      /* Danger badge */
.badge-warning     /* Warning badge */

.result            /* Result message container */
.success, .ok      /* Success message */
.error, .bad       /* Error message */
.warning           /* Warning message */
.info              /* Info message */
```

### Tables
```css
.table-container   /* Scrollable table wrapper */
table              /* Table element */
thead, th          /* Table headers */
tbody, td          /* Table body/cells */
```

### Tabs
```css
.tabs              /* Tab navigation */
.tab               /* Individual tab */
.tab.active        /* Active tab */
.tab-content       /* Tab content area */
.tab-content.active /* Visible content */
```

### Utilities
```css
.hidden            /* Hide element */
.visible           /* Show element */
.text-center       /* Center text */
.text-right        /* Right align text */
.flex              /* Flexbox */
.flex-col          /* Flex column */
.items-center      /* Align items center */
.justify-between   /* Space between */
.gap-sm, .gap-md, .gap-lg  /* Flex gaps */
.mt-sm, .mt-md, .mt-lg     /* Margin top */
.mb-sm, .mb-md, .mb-lg     /* Margin bottom */
.w-full            /* Full width */
```

## 🎨 CSS Variables

### Colors
```css
--bg               /* Background */
--panel            /* Panel background */
--panel-2          /* Lighter panel */
--panel-3          /* Even lighter */
--border           /* Border color */
--border-light     /* Lighter border */
--text             /* Primary text */
--text-secondary   /* Secondary text */
--muted            /* Muted text */
--primary          /* Primary blue */
--success          /* Success green */
--danger           /* Danger red */
--warning          /* Warning orange */
--info             /* Info cyan */
```

### Spacing
```css
--spacing-xs       /* 4px */
--spacing-sm       /* 8px */
--spacing-md       /* 16px */
--spacing-lg       /* 24px */
--spacing-xl       /* 32px */
```

### Typography
```css
--font-xs          /* Extra small font */
--font-sm          /* Small font */
--font-base        /* Base font */
--font-md          /* Medium font */
--font-lg          /* Large font */
--font-xl          /* Extra large font */
```

### Border Radius
```css
--radius-sm        /* 6px */
--radius-md        /* 10px */
--radius-lg        /* 14px */
```

## 📱 Responsive Breakpoints

### Mobile (< 768px)
- Hamburger menu
- Single column layouts
- Stacked cards
- Full-width buttons

### Tablet (768px - 1024px)
- 2-column grids
- Optimized spacing
- Readable fonts

### Desktop (> 1024px)
- Multi-column grids
- Full navigation
- Maximum density

## 🚀 Common Patterns

### Page Structure
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Page Title | Shoonya Platform</title>
    <link rel="stylesheet" href="/web/styles/common.css">
</head>
<body>
    <header><!-- Navigation --></header>
    <main>
        <div class="page-header">
            <h1>Page Title</h1>
            <p class="muted">Description</p>
        </div>
        <!-- Content -->
    </main>
    <script><!-- JavaScript --></script>
</body>
</html>
```

### Card with Form
```html
<div class="card">
    <div class="card-header">
        <h3 class="card-title">Form Title</h3>
    </div>
    <div class="card-body">
        <div class="row">
            <div class="field">
                <label>Label</label>
                <input type="text" placeholder="Placeholder">
            </div>
        </div>
    </div>
    <div class="card-footer">
        <button class="btn-primary">Submit</button>
    </div>
</div>
```

### Status Grid
```html
<div class="grid grid-cols-4">
    <div class="status-box">
        <div class="muted">Label</div>
        <div style="font-weight:600; margin-top:4px;">Value</div>
    </div>
</div>
```

### Tab System
```html
<div class="tabs">
    <div class="tab active" onclick="switchTab('tab1')">Tab 1</div>
    <div class="tab" onclick="switchTab('tab2')">Tab 2</div>
</div>

<div id="tab1Content" class="tab-content active">
    <!-- Content -->
</div>
<div id="tab2Content" class="tab-content">
    <!-- Content -->
</div>

<script>
function switchTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById(tabName + 'Content').classList.add('active');
    event.target.classList.add('active');
}
</script>
```

### Data Table
```html
<div class="table-container">
    <table>
        <thead>
            <tr>
                <th>Column 1</th>
                <th>Column 2</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Data 1</td>
                <td>Data 2</td>
            </tr>
        </tbody>
    </table>
</div>
```

## 🎯 Strategy Page Usage

### Access Strategy Management
1. Click "Strategy" in navigation
2. Select strategy type from dropdown
3. Configure rules in 4 tabs:
   - Entry Rules
   - Adjustment Rules
   - Exit Rules
   - Risk Management
4. Monitor live positions in Monitor tab
5. Control strategy with Start/Pause/Stop buttons

### Supported Strategy Types
- Custom Strategy (generic)
- Delta Neutral Straddle/Strangle
- Iron Condor
- Butterfly
- Long/Short Straddle
- Directional Spreads

---

**Quick Tips:**
- Use CSS variables for colors: `color: var(--primary)`
- All spacing uses the spacing scale
- Typography auto-scales on mobile
- Always wrap tables in `.table-container`
- Use `.row` for auto-responsive 2-column layouts
