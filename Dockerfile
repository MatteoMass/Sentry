# Sentry, in two stages: node builds the frontend, python serves it.
#
# The API mounts `src/frontend/dist/` at `/`, exactly as `build_and_run.sh`
# arranges it locally, so the runtime image needs node only long enough to
# produce that folder — the first stage does it and nothing of node survives
# into the image that ships.
#
#   docker build -t sentry .                     the whole thing
#   docker build --target frontend -t sentry-fe .  the frontend build alone

# ----------------------------------------------------------------- frontend

FROM node:22-alpine AS frontend

WORKDIR /app/src/frontend

# The manifests travel first so the install is only redone when they move,
# and not on every edit to a component.
COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci

COPY src/frontend/ ./

# `npm run build` is `vue-tsc --build && vite build`: the types are checked
# here, so a build that succeeds is a build the backend can serve.
RUN npm run build

# ------------------------------------------------------------------ backend

FROM python:3.14-slim AS runtime

# ffmpeg and ffprobe re-encode the recordings before they travel; the
# pipeline looks them up on the PATH, so the Homebrew paths written in
# `sentry.yml` are overruled by SENTRY_FFMPEG / SENTRY_FFPROBE below.
RUN apt-get update \
 && apt-get install --no-install-recommends -y ffmpeg \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    # No virtualenv: the container is the environment, so the packages go
    # straight into the system interpreter and `poetry run` is not needed.
    POETRY_VIRTUALENVS_CREATE=false

RUN pip install "poetry>=2,<3"

WORKDIR /app

# Same reason as the frontend: the lock file changes far less often than the
# sources, so the dependency layer survives most rebuilds.
COPY pyproject.toml poetry.lock ./
RUN poetry install

COPY src/ ./src/
COPY sentry.yml ./sentry.yml

# The build from the first stage, where `paths.frontend_dist` expects it.
COPY --from=frontend /app/src/frontend/dist ./src/frontend/dist

# Where the recordings and the database land. Bind-mount or name a volume
# over it, or the data lives and dies with the container.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# The file says 127.0.0.1, which inside a container answers nobody outside
# it; these win over the file, and the flags below win over these.
ENV SENTRY_HOST=0.0.0.0 \
    SENTRY_PORT=8016 \
    SENTRY_STORAGE_ROOT=/app/data \
    SENTRY_FRONTEND_DIST=/app/src/frontend/dist \
    SENTRY_FFMPEG=/usr/bin/ffmpeg \
    SENTRY_FFPROBE=/usr/bin/ffprobe

EXPOSE 8016

# GEMINI_API_KEY is not baked in: pass it with `--env-file .env` or `-e`.
CMD ["uvicorn", "backend:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8016"]
