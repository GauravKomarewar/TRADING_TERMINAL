# Dashboard V2

React + TypeScript dashboard served in production at `/v2/`.

## Local development

```bash
npm install
npm run dev
```

The Vite dev server runs on port `3000` and proxies dashboard/auth requests to `http://127.0.0.1:8000`.

## Production build

```bash
npm run build
```

The built bundle is emitted to `dist/` and is served on this server through nginx at:

- `https://129.154.41.30/v2/`

## Current status

- Live data: dashboard snapshot, orderbook, strategies, diagnostics, charts, option chain, telegram preferences.
- Read-only by design: strategy builder, until the v2 editor matches the production strategy schema safely.
- Preview: settings page.
