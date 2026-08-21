# Sentry frontend

Vue 3 + Vite + TypeScript. Two panes: the folder tree with the recordings on
the left, the details of the selected recording in the middle.

## Development

```bash
npm install
npm run dev          # http://localhost:5173
```

Vite proxies `/folders` and `/recordings` to `http://127.0.0.1:8000`, so run
the API next to it:

```bash
uvicorn backend:app --app-dir src --reload
```

Point the proxy elsewhere with `SENTRY_API_URL`.

## Build

```bash
npm run build        # type check, then dist/
```

`dist/` is what the backend serves: [`api/frontend.py`](../api/frontend.py)
mounts it at `/` when it exists, so `uvicorn backend:app --app-dir src` alone
serves both the API and the app. Without a build the service still starts and
answers the API only. `SENTRY_FRONTEND_DIST` overrides where the build is
looked for, which is what an image building the app elsewhere will use.

## Layout

| Path                      | What lives there                                  |
| ------------------------- | ------------------------------------------------- |
| `src/api/`                | The only place that talks HTTP, and its payloads. |
| `src/composables/`        | The shared state: tree, recordings, selection.    |
| `src/components/`         | The sidebar, the recursive tree row, the detail.  |
| `src/styles/main.css`     | Tokens, light and dark.                           |
