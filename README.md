# Sentry

[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14+-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Vue 3](https://img.shields.io/badge/Vue_3-4FC08D?style=flat-square&logo=vuedotjs&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-8E75B2?style=flat-square&logo=googlegemini&logoColor=white)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](Dockerfile)
[![Built with Claude Code](https://img.shields.io/badge/built_with-Claude_Code-D97757?style=flat-square&logo=claude&logoColor=white)](https://claude.com/claude-code)

<p align="center">
  <img src="assets/readme_image.png" alt="Sentry — a griffin in headphones reading a diarized transcript" width="320">
</p>

Sentry listens to your recordings so you don't have to listen to them twice.

A meeting, a call, a voice memo: an hour of talk that holds maybe five
minutes worth keeping, and no way to find them again except by living through
the hour a second time. Sentry takes the file, transcribes it with the
speakers told apart, and writes down what it was about — what stood out, what
was decided, who owes what to whom — then files the whole thing in a tree you
can browse and annotate.

It runs as one process on your own machine: a FastAPI service that stores the
recordings and drives the pipeline, and a Vue app the same service serves. The
recordings stay on your disk, in plain folders you can open with anything.
The only thing that leaves the machine is the audio, on its way to Gemini.

## What happens to a recording

An upload lands in `to_process` and waits there — the API stores bytes and
nothing else. Asked to run, the pipeline does two things, in this order
because the second needs the first:

1. **Transcription and diarization.** ffmpeg re-encodes the media to what a
   recogniser actually reads — one channel, 16 kHz, in the smallest encoding
   that still fits the request — and cuts it into pieces of a few minutes.
   Each piece goes to Gemini, which writes the words and says which voice
   said them. A roster of the voices heard so far and the last seconds of the
   previous piece travel with every request, so the speaker called `1` at
   minute four is still `1` at minute six.
2. **Summary.** The diarized dialogue, timestamps and labels included, goes to
   the model with the shape a reader needs: the subject, the points that stood
   out, the decisions, the commitments and who made them. A section with
   nothing in it is left empty, because an invented decision is worse than a
   missing one.

Every step writes its result to disk before the next one starts, which is what
makes the pipeline cheap to resume: a summary that failed is retried against
the transcript already paid for, and only `force` makes the audio travel
again. That is also why there are two statuses and not one — a recording that
transcribed but failed to summarise settles in `error` with its transcript
still there to read.

```
to_process → transcribing → transcribed → summarizing → processed
                   │                           │
                   └─────────→ error ←─────────┘
```

A recording's folder holds the result as files, not as rows:

```
data/recordings/<id>/
├── recording.mp4      the media as it was uploaded
├── transcript.json    the diarized transcript, for the app
├── transcript.txt     the same, for a human
├── summary.json       the sections, as the model returned them
├── summary.md         the same, rendered
├── notes.md           what you typed about it
└── attachments/       the screenshots you kept beside it
```

The notes half is yours and the pipeline never touches it: a note and its
attachments survive every run, including one that transcribes the audio from
scratch, and they travel in the archive when the recording is downloaded.

## Asking instead of reading

A transcript answers everything and says nothing: what somebody wants from an
hour of talk is usually one sentence, and finding it by reading is the work
worth skipping. Two things in the app do that.

The **search** walks the dialogue. Every line holding the words is marked
where it stands — the transcript is never filtered down to what matches,
because a line is worth reading with the ones around it — and the arrows step
between them without moving the player.

**Ask Sentry** is the tab that asks. A question goes to the model with the
recording behind it, and what the recording contributes is yours to choose,
because it is what the call costs: the summary is a page, the transcript is a
book, and the source is the whole hour of audio re-encoded and uploaded again
**on every turn**. The first two are on, the third is off and asks before it
goes on.

Nothing about a conversation is stored, on either side. It lives in the
browser and travels whole with every question, so leaving the tab ends it —
which is the honest behaviour for something nobody is paying to keep.

## Requirements

- Python ≥ 3.14 and [Poetry](https://python-poetry.org/)
- Node.js ≥ 20 and npm — only to build the frontend
- ffmpeg and ffprobe on the PATH (or named in `sentry.yml`)
- A Gemini API key, for the transcription, the summary and the questions

Docker needs none of them: the image brings its own.

## Setup

```bash
cp example.env .env   # then fill in GEMINI_API_KEY
```

`.env` carries the secrets and nothing else. It is read once when the server
starts and never overrides a variable that is already set, so a deployment
passing its own can ignore the file entirely. Everything that is not a secret
lives in [`sentry.yml`](sentry.yml), where every key is optional and every key
is commented — see [Configuration](#configuration).

## Run

### Locally

```bash
./build_and_run.sh
```

That builds the frontend and then serves it together with the API on
<http://127.0.0.1:8016> — the built app is mounted at `/`, so one process
answers both. The interactive API documentation is at `/docs`.

The script installs what is missing before it starts: the npm dependencies
when `node_modules` is absent or older than the lock file, and the Poetry
environment when the project has never been installed.

| Option           | What it does                                           |
| ---------------- | ------------------------------------------------------ |
| `--no-build`     | Skip the frontend build and serve the current `dist/`.  |
| `--reload`       | Restart the backend when the Python sources change.     |
| `--port <n>`     | Serve on another port. Default `8016`.                  |
| `--host <addr>`  | Bind elsewhere — `0.0.0.0` to accept from the network.  |
| `--help`         | Print the same, from the script itself.                 |

The address comes from `server.host` and `server.port` in `sentry.yml`, or
from `SENTRY_HOST` and `SENTRY_PORT`; the flags win over both.

Without a build the service still starts and answers the API only, so
`./build_and_run.sh --no-build` on a fresh checkout is an API-only server, not
an error.

### With Docker

```bash
docker compose up --build
```

Same thing on <http://localhost:8016>, with nothing installed on the host.
[`Dockerfile`](Dockerfile) is the same two steps in two stages: node builds
the frontend, python serves it, and nothing of node survives into the image
that ships. ffmpeg comes from the image, and `SENTRY_FFMPEG` / `SENTRY_FFPROBE`
point at it whatever `sentry.yml` says about Homebrew.

[`docker-compose.yml`](docker-compose.yml) reads `.env` for the API key,
mounts `./data` so the recordings outlive the container, and mounts
`./sentry.yml` read-only so a setting can be changed with a restart instead of
a rebuild.

The frontend build is also available on its own, writing into the checkout so
a local run can serve it:

```bash
docker compose --profile build run --rm frontend-build   # → src/frontend/dist
./build_and_run.sh --no-build
```

### By hand

The script does nothing that cannot be done in four commands:

```bash
npm --prefix src/frontend ci
npm --prefix src/frontend run build
poetry install
poetry run uvicorn backend:app --app-dir src --port 8016
```

## Development

With the frontend changing, run Vite next to the API instead of rebuilding:

```bash
./build_and_run.sh --no-build --reload --port 8000   # the API, restarting
npm --prefix src/frontend run dev                    # http://localhost:5173
```

Vite proxies `/folders`, `/recordings` and `/prompts` to
`http://127.0.0.1:8000`, so the app uses the same relative URLs it does when
the backend serves it. Point the proxy elsewhere with `SENTRY_API_URL`. A
frontend that calls the API directly instead of through the proxy needs its
origin in `server.cors_origins`; through the proxy it needs nothing.

## How it is put together

Four layers, from the outside in.

### Connectors — `src/connectors/`

Everything that talks to something outside the process, behind an interface
that hides which something it is.

- **`memory_connector/`** is the storage, and the only thing that knows where
  a byte lands. A SQLite file holds the tabular side — the folder tree, the
  index of recordings and their statuses, and a key/value store of what the
  user changed by hand — while the recordings themselves are folders on disk,
  one per recording, holding the media and whatever the pipeline wrote next to
  it. The two sides are deliberately ignorant of each other: the blob side
  never asks whether a recording is registered, which is what lets a folder be
  opened, copied or backed up with ordinary tools.
- **`genai_connectors/`** is the generative provider behind a vendor-agnostic
  surface — `generate`, `stream`, a `Message` that can carry media, a token
  count. Gemini is the only implementation there is; it is not the only one
  the code allows.

### Core — `src/core/`

The business logic: from a stored recording to what it was about.
`ProcessingPipeline` is the whole of it seen from outside, and the only thing
an entrypoint needs to know. Inside: `audio` cuts and re-encodes with ffmpeg,
`speech` is the contract a speech-to-text backend answers to and
`gemini_speech` the one implementation, `summarizer` distils the transcript,
`chat` answers what is asked about a recording, `prompts` is the catalogue of
the system prompts and of the overrides stored for them, and `notes` is the
human half of a recording's folder. The layer knows nothing of HTTP.

### Backend — `src/backend.py`, `src/api/`, `src/config.py`

`backend.py` only assembles: it opens the storage and the pipeline for the
life of the process, registers the routers, and translates connector errors
into status codes — so no endpoint has to. The endpoints themselves are in
`api/`, one module per resource:

| Router                          | What it is for                                          |
| ------------------------------- | ------------------------------------------------------- |
| `/folders`                      | The tree: create, rename, move, delete, list.            |
| `/recordings`                   | Upload, list, rename, move, delete, download an archive. |
| `/recordings/{id}/process`      | Run the pipeline — or just `/transcribe`, `/summarize`.  |
| `/recordings/{id}/transcript`, `/summary`, `/media` | What came out of it.         |
| `/recordings/{id}/chat`         | Ask a question about it, over what you choose to send.   |
| `/recordings/{id}/notes`        | The note and its attachments.                            |
| `/prompts`                      | Read, rewrite and reset the system prompts.              |

`config.py` assembles the settings once, when it is imported, out of the three
layers described below.

### Frontend — `src/frontend/`

Vue 3, Vite and TypeScript. Two panes: the folder tree with the recordings on
the left, the details of the selected one in the middle — the player, the
buttons that start the pipeline, and four tabs beside them: the summary, the
searchable transcript, Ask Sentry, and the note with its attachments.
`src/api/` is the only place that talks HTTP, `src/composables/` holds the
shared state, and `src/styles/main.css` the tokens for both themes. It has its own
[README](src/frontend/README.md).

The build lands in `dist/`, which the API mounts at `/` when it is there. The
mount goes last, after every router, so it catches what the routes did not —
and a checkout that has never run `npm run build` still starts, and answers
the API alone.

## Configuration

Three layers decide every setting, and they win in this order:

1. the defaults in [`src/config.py`](src/config.py), which is what a checkout
   with nothing configured runs on;
2. [`sentry.yml`](sentry.yml) at the root of the project — or wherever
   `SENTRY_CONFIG_FILE` says — which is where an installation writes down what
   it wants differently;
3. the environment, which overrules both, so a container passing its own
   values keeps them whatever the file says.

The file is read once, when the server starts, and a missing file is not an
error. A file that is there and unparseable is: the service refuses to start
rather than run on settings nobody asked for. A single value that cannot be
read is reported and the layer below answers instead.

| Section         | What you can change                                                                                                     |
| --------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `paths`         | Where the recordings and the database live, where the built frontend is looked for, which ffmpeg and ffprobe are called.  |
| `server`        | Host and port, the origins allowed to call the API from a browser, the largest upload accepted.                           |
| `logging`       | Level of the root logger.                                                                                                 |
| `transcription` | Which model listens, the language it is told to expect, how long each piece of audio is, how much of the previous piece travels with it, the ceiling on one request, the timeout and how many times a piece is retried. |
| `audio`         | Sample rate, the encodings tried in order — `flac` loses nothing, `opus` fits roughly five times more audio — and the bitrate of the lossy one. |
| `summarization` | Which model writes, how freely (`temperature`), how much transcript it is given, and the cap on its answer.               |
| `chat`          | Which model answers a question about a recording, how freely, how much transcript travels with it, the cap on the answer, and the ceiling on the audio when the source is sent. |
| `pipeline`      | Whether an upload starts processing by itself instead of waiting to be asked.                                             |

Every key in `sentry.yml` is documented in place, with its default and the
environment variable that overrules it — `SENTRY_TRANSCRIPTION_MODEL`,
`SENTRY_AUDIO_ENCODINGS`, and so on for all of them.

Secrets are not in there. `GEMINI_API_KEY` — the only key the pipeline needs —
is read from the environment alone, which is what [`.env`](example.env) is
for; `SENTRY_ENV_FILE` says where to read that from when it is not the `.env`
at the root.

The three prompts — transcription, summary, Ask Sentry — are configured in
neither file. They are stored in the database and rewritten from the app
itself, so an edit reaches the next call without a restart, and the default stays untouched underneath: resetting a
prompt is a delete, and an improved default reaches every installation that
never disagreed with it.

## Layout

| Path                | What lives there                                             |
| ------------------- | ------------------------------------------------------------ |
| `src/backend.py`    | Assembles the app: routers, errors, lifespan.                 |
| `src/config.py`     | The settings, and the three layers behind them.               |
| `src/api/`          | The endpoints and their payloads.                             |
| `src/connectors/`   | Storage and generative providers, behind interfaces.          |
| `src/core/`         | The processing pipeline.                                      |
| `src/frontend/`     | The Vue app — see its own [README](src/frontend/README.md).   |
| `sentry.yml`        | Every setting, commented, with its environment variable.      |
| `build_and_run.sh`  | Build the frontend, then serve everything.                    |
| `Dockerfile`        | The same, in two stages.                                      |
| `data/`             | The database and one folder per recording. Not in git.        |

## License

[MIT](LICENSE).
