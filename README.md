# Sentry

Recordings, and where each one sits in the processing pipeline. A FastAPI
service that stores the recordings, transcribes them with Gemini and writes a
summary, plus a Vue frontend the same service serves.

## Requirements

- Python ≥ 3.14 and [Poetry](https://python-poetry.org/)
- Node.js ≥ 20 and npm — only to build the frontend
- A Gemini API key, for the transcription and the summary

## Setup

```bash
cp example.env .env               # then fill in GEMINI_API_KEY
cp sentry.example.yml sentry.yml  # optional: everything in it has a default
```

`.env` carries the secrets and nothing else; it is read once when the server
starts and never overrides a variable that is already set, so a deployment
passing its own can ignore it. `sentry.yml` carries the settings — where the
recordings live, which models are called, how the audio is cut, what the
service listens on — and every key in it is optional. See
[Configuration](#configuration).

## Run

```bash
./run.sh
```

That builds the frontend and then serves it together with the API on
<http://127.0.0.1:8016> — the built app is mounted at `/`, so one process
answers both. The interactive API documentation is at `/docs`.

The script installs what is missing before it starts: the npm dependencies
when `node_modules` is absent or older than the lock file, and the Poetry
environment when the project has never been installed.

| Option           | What it does                                        |
| ---------------- | --------------------------------------------------- |
| `--no-build`     | Skip the frontend build and serve the current `dist/`. |
| `--reload`       | Restart the backend when the Python sources change.  |
| `--port <n>`     | Serve on another port. Default `8016`.               |
| `--host <addr>`  | Bind elsewhere — `0.0.0.0` to accept from the network. |
| `--help`         | Print the same, from the script itself.              |

The address comes from `server.host` and `server.port` in `sentry.yml`, or
from `SENTRY_HOST` and `SENTRY_PORT`; the flags win over both.

Without a build the service still starts and answers the API only, so
`./run.sh --no-build` on a fresh checkout is an API-only server, not an
error.

### By hand

The script does nothing that cannot be done in two commands:

```bash
npm --prefix src/frontend ci
npm --prefix src/frontend run build
poetry install
poetry run uvicorn backend:app --app-dir src --port 8016
```

## Development

With the frontend changing, run Vite next to the API instead of rebuilding:

```bash
./run.sh --no-build --reload --port 8000   # the API, restarting on change
npm --prefix src/frontend run dev          # http://localhost:5173
```

Vite proxies `/folders`, `/recordings` and `/prompts` to
`http://127.0.0.1:8000`, so the app uses the same relative URLs it does when
the backend serves it. Point the proxy elsewhere with `SENTRY_API_URL`. A
frontend that calls the API directly instead of through the proxy needs its
origin in `server.cors_origins`; through the proxy it needs nothing.

## Configuration

Three layers decide every setting, and they win in this order:

1. the defaults in [`src/config.py`](src/config.py), which is what a checkout
   with nothing configured runs on;
2. `sentry.yml` at the root of the project — or wherever `SENTRY_CONFIG_FILE`
   says — which is where an installation writes down what it wants
   differently;
3. the environment, which overrules both, so a container passing its own
   values keeps them whatever the file says.

The file is read once, when the server starts, and a missing file is not an
error. A file that is there and unparseable is: the service refuses to start
rather than run on settings nobody asked for. A single value that cannot be
read is reported and the layer below answers instead.

| Section         | What it decides                                              |
| --------------- | ------------------------------------------------------------ |
| `paths`         | Storage root, built frontend, ffmpeg and ffprobe.             |
| `server`        | Host, port, CORS origins, largest upload accepted.            |
| `logging`       | Level of the root logger.                                     |
| `transcription` | Model, language, chunk length, context, timeout, attempts.    |
| `audio`         | Sample rate, encodings to try, Opus bitrate.                  |
| `summarization` | Model, temperature, how much transcript travels, token cap.   |
| `pipeline`      | Whether an upload starts processing by itself.                |

[`sentry.example.yml`](sentry.example.yml) documents every key, with its
default and the environment variable that overrules it.

Secrets are not in there. `GEMINI_API_KEY` — the only key the pipeline needs —
is read from the environment alone, which is what [`.env`](example.env) is
for; `SENTRY_ENV_FILE` says where to read that from when it is not the `.env`
at the root.

The two prompts are configured neither here nor there: they are stored in the
database and rewritten from the app, at `/prompts`, so an edit reaches the
next run without a restart.

## Layout

| Path                      | What lives there                                  |
| ------------------------- | ------------------------------------------------- |
| `src/backend.py`          | Assembles the app: routers, errors, lifespan.     |
| `src/config.py`           | The settings, and the three layers behind them.   |
| `src/api/`                | The endpoints and their payloads.                 |
| `src/connectors/`         | Storage: the folders, the recordings, the database. |
| `src/core/`               | The processing pipeline.                          |
| `src/frontend/`           | The Vue app — see its own [README](src/frontend/README.md). |
