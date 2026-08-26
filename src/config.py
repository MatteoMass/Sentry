"""Settings shared by every entrypoint of Sentry.

The API and the processing worker are separate processes that must agree on
where the recordings live and on what the pipeline is allowed to do, so every
setting is resolved here and nowhere else. What the rest of the code sees is
:data:`settings`: one frozen object, read once, that the modules take their
defaults from instead of reaching for the environment on their own.

Three layers decide a value, and they win in this order:

1. the defaults written in the dataclasses below, which is what a checkout
   with nothing configured runs on;
2. ``sentry.yml`` at the root of the project — or wherever
   ``SENTRY_CONFIG_FILE`` says — which is where an installation writes down
   what it wants differently;
3. the environment, which overrules both, so a container passing its own
   values keeps them whatever the file happens to say.

Secrets are not part of that. ``GEMINI_API_KEY`` has no key in the file on
purpose: a configuration file is committed and a key is not, so it is read
from the environment alone, which is where :func:`load_environment` puts what
``.env`` carries.

This is also where the environment is assembled. Importing this module loads
the ``.env`` file sitting at the root of the project, because that has to
happen before anything reads a variable — and by the time an entrypoint has
imported its settings, it already has: the frontend directory is resolved
while the application is being built, long before the first request.

Paths are used as they are written: a relative one is read against the
working directory the process was started in, which is the root of the
project for anything ``run.sh`` launches.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
"""Directory holding ``pyproject.toml``, one level above the sources."""

ENV_FILE_ENV = "SENTRY_ENV_FILE"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

CONFIG_FILE_ENV = "SENTRY_CONFIG_FILE"
DEFAULT_CONFIG_FILES = (PROJECT_ROOT / "sentry.yml", PROJECT_ROOT / "sentry.yaml")
"""Where the file is looked for when nothing names it; the first one wins."""

API_KEY_ENV = "GEMINI_API_KEY"
FALLBACK_API_KEY_ENV = "GOOGLE_API_KEY"

DEFAULT_STORAGE_ROOT = Path("./data")
DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"


class ConfigError(RuntimeError):
    """Raised when a configuration file exists but cannot be used.

    A file that is there and unreadable is a mistake worth stopping for: the
    alternative is a service that silently runs on defaults nobody asked for.
    A file that is simply absent is not an error at all.
    """


# ------------------------------------------------------------------ sections


@dataclass(frozen=True, slots=True)
class Paths:
    """Where things live on the machine running the service.

    Attributes:
        storage_root: Directory holding the database and the recording
            folders.
        frontend_dist: Directory holding the built single page application.
        ffmpeg: Executable to encode with. ``None`` looks it up on the PATH.
        ffprobe: Executable to read durations with. ``None`` looks it up on
            the PATH.
    """

    storage_root: Path = DEFAULT_STORAGE_ROOT
    frontend_dist: Path = DEFAULT_FRONTEND_DIST
    ffmpeg: str | None = None
    ffprobe: str | None = None


@dataclass(frozen=True, slots=True)
class Server:
    """How the HTTP service is exposed.

    Attributes:
        host: Address to bind to. ``0.0.0.0`` accepts from the network.
        port: Port to listen on.
        cors_origins: Origins allowed to call the API from a browser. Empty —
            the default — installs no CORS at all, which is right when the
            same process serves the frontend.
        max_upload_mb: Largest recording accepted, in mebibytes. ``None``
            accepts whatever arrives.
    """

    host: str = "127.0.0.1"
    port: int = 8016
    cors_origins: tuple[str, ...] = ()
    max_upload_mb: float | None = None

    @property
    def max_upload_bytes(self) -> int | None:
        """The upload ceiling in bytes, or ``None`` when there is none."""
        if self.max_upload_mb is None:
            return None
        return int(self.max_upload_mb * 1024 * 1024)


@dataclass(frozen=True, slots=True)
class Logs:
    """What the process writes about itself.

    Attributes:
        level: Threshold of the root logger, as :mod:`logging` names it.
    """

    level: str = "INFO"


@dataclass(frozen=True, slots=True)
class Transcription:
    """How the audio is sent to be transcribed and diarized.

    Attributes:
        model: Model that does the listening.
        language: Language the recordings are expected in, as a BCP-47 tag.
            It is a hint: the transcript records whatever is actually spoken.
        chunk_minutes: How long each piece of audio lasts. Shorter pieces
            answer faster and time out less; longer ones leave fewer seams
            where a voice could be given a new number.
        context_seconds: How much of the previous piece travels with each
            request so the voices can be matched across the seam.
        max_inline_mb: Ceiling on the audio of one request. The bytes travel
            base64 encoded, which inflates them by a third, so this sits well
            under the one the API documents.
        timeout_seconds: How long one request may take.
        attempts: How many times a piece is tried before the recording is
            given up on.
        max_output_tokens: Room the model is given to answer in. A piece of
            speech dense enough to overrun it comes back as JSON cut in half,
            so the ceiling is raised well above what a few minutes of dialogue
            weigh rather than left at whatever the provider defaults to.
    """

    model: str = "gemini-3.1-flash-lite"
    language: str = "it-IT"
    chunk_minutes: float = 5.0
    context_seconds: float = 20.0
    max_inline_mb: float = 12.0
    timeout_seconds: float = 600.0
    attempts: int = 2
    max_output_tokens: int = 32_768

    @property
    def chunk_seconds(self) -> float:
        """The piece length in seconds, which is what the cutting takes."""
        return self.chunk_minutes * 60

    @property
    def max_inline_bytes(self) -> int:
        """The ceiling on one request in bytes."""
        return int(self.max_inline_mb * 1024 * 1024)


@dataclass(frozen=True, slots=True)
class Audio:
    """How the media is re-encoded before it travels.

    Attributes:
        sample_rate: Rate the audio is resampled to, in hertz.
        encodings: Encodings to try, in order of preference: the first one
            that fits the request is the one that is sent.
        opus_bitrate: Bitrate of the Opus fallback, as ffmpeg reads it.
    """

    sample_rate: int = 16_000
    encodings: tuple[str, ...] = ("flac", "opus")
    opus_bitrate: str = "24k"


@dataclass(frozen=True, slots=True)
class Summarization:
    """How the transcript is turned into what is worth remembering.

    Attributes:
        model: Model that writes the summary.
        temperature: Sampling temperature. A low one keeps the summary close
            to what was said.
        max_characters: Longest dialogue sent in one go, past which the tail
            is dropped, so a pathological transcript degrades into a partial
            summary instead of a rejected request.
        max_output_tokens: Upper bound on the answer. ``None`` leaves it to
            the provider.
    """

    model: str = "gemini-3.1-flash-lite"
    temperature: float = 0.2
    max_characters: int = 400_000
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Chat:
    """How a question asked about a recording is answered.

    Attributes:
        model: Model that answers.
        temperature: Sampling temperature. It sits above the summariser's: an
            answer is allowed to be a sentence rather than a heading, and
            still says only what the recording says.
        max_characters: Longest dialogue sent with a question, past which the
            tail is dropped, so a pathological transcript degrades into a
            partly informed answer instead of a rejected request.
        max_output_tokens: Upper bound on the answer. ``None`` leaves it to
            the provider.
        max_source_mb: Ceiling on the audio sent when the recording itself is
            asked for, in mebibytes. As with the transcription, the bytes
            travel base64 encoded, so this sits under the limit the API
            documents; a recording above it is re-encoded to Opus rather than
            refused.
    """

    model: str = "gemini-3.1-flash-lite"
    temperature: float = 0.4
    max_characters: int = 400_000
    max_output_tokens: int | None = None
    max_source_mb: float = 12.0

    @property
    def max_source_bytes(self) -> int:
        """The ceiling on the audio of one question, in bytes."""
        return int(self.max_source_mb * 1024 * 1024)


@dataclass(frozen=True, slots=True)
class Pipeline:
    """What happens to a recording without anybody asking.

    Attributes:
        auto_process_on_upload: Start the whole pipeline as soon as a
            recording is uploaded, instead of waiting for the endpoint that
            asks for it.
    """

    auto_process_on_upload: bool = False


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the entrypoints agree on, resolved once.

    Attributes:
        paths: Where the storage, the build and the tools are.
        server: How the service is exposed.
        logging: What the process writes about itself.
        transcription: How the audio is transcribed.
        audio: How the audio is encoded.
        summarization: How the summary is written.
        chat: How a question asked about a recording is answered.
        pipeline: What runs by itself.
        gemini_api_key: The key the provider is called with, read from the
            environment alone. ``None`` when none is set, which is not fatal:
            only the pipeline needs it, and only when it runs.
        config_file: The YAML that was read, or ``None`` if there was none.
        env_file: The ``.env`` that was read, or ``None`` if there was none.
    """

    paths: Paths = field(default_factory=Paths)
    server: Server = field(default_factory=Server)
    logging: Logs = field(default_factory=Logs)
    transcription: Transcription = field(default_factory=Transcription)
    audio: Audio = field(default_factory=Audio)
    summarization: Summarization = field(default_factory=Summarization)
    chat: Chat = field(default_factory=Chat)
    pipeline: Pipeline = field(default_factory=Pipeline)
    gemini_api_key: str | None = field(default=None, repr=False)
    config_file: Path | None = None
    env_file: Path | None = None


SECTIONS = (
    "paths",
    "server",
    "logging",
    "transcription",
    "audio",
    "summarization",
    "chat",
    "pipeline",
)
"""Top level keys the file may hold; anything else is a typo worth saying so."""


# ------------------------------------------------------------------- reading


def load_environment() -> Path | None:
    """Read the ``.env`` file into the environment, if there is one.

    The file is the one at the root of the project, unless ``SENTRY_ENV_FILE``
    names another — a deployment holding its secrets elsewhere says so there.
    A missing file is not an error: everything it would carry can be set the
    ordinary way, and in production usually is.

    Returns:
        The file that was read, or ``None`` when there was none to read.
    """
    location = Path(os.getenv(ENV_FILE_ENV, DEFAULT_ENV_FILE)).expanduser()
    if not location.is_file():
        return None

    # A variable already in the environment wins: the file is a convenience
    # for a checkout, not a way to overrule what a container was started with.
    load_dotenv(location, override=False)
    return location


def config_location() -> Path | None:
    """Return the configuration file to read, or ``None`` when there is none.

    ``SENTRY_CONFIG_FILE`` names it outright; without it the two usual names
    at the root of the project are tried, in order.
    """
    named = os.getenv(CONFIG_FILE_ENV)
    if named:
        location = Path(named).expanduser()
        if not location.is_file():
            raise ConfigError(f"No configuration file at {str(location)!r}.")
        return location

    return next((path for path in DEFAULT_CONFIG_FILES if path.is_file()), None)


def load_config_file() -> tuple[Path | None, dict[str, Any]]:
    """Read the YAML file into a mapping, if there is one to read.

    Returns:
        The file that was read and what it holds; ``(None, {})`` when there
        is no file, and an empty mapping when the file is empty.

    Raises:
        ConfigError: If the file cannot be parsed, or holds anything other
            than a mapping of sections.
    """
    location = config_location()
    if location is None:
        return None, {}

    try:
        document = yaml.safe_load(location.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ConfigError(f"{location} could not be read: {error}") from error

    if document is None:
        return location, {}
    if not isinstance(document, dict):
        raise ConfigError(
            f"{location} must hold a mapping of sections, not "
            f"{type(document).__name__}."
        )

    for key in document:
        if key not in SECTIONS:
            logger.warning("Ignoring unknown section %r in %s", key, location)
    return location, document


@dataclass(frozen=True, slots=True)
class _Section:
    """One section of the file, and the environment that overrules it."""

    name: str
    values: dict[str, Any]

    def read[T](
        self,
        key: str,
        variable: str,
        cast: Callable[[Any], T],
        default: T,
    ) -> T:
        """Return the value of one setting, from the first layer that has it.

        The environment is asked first and the file second, so a container
        keeps what it was started with. A value that cannot be read is not
        worth refusing the service over: it is reported and the layer below
        answers instead.
        """
        for origin, raw in (
            (variable, os.getenv(variable)),
            (f"{self.name}.{key}", self.values.get(key)),
        ):
            if raw is None:
                continue
            try:
                return cast(raw)
            except (TypeError, ValueError) as error:
                logger.warning("Ignoring %s: %s", origin, error)
        return default


def _section(document: dict[str, Any], name: str) -> _Section:
    """Return one section of the document, empty when it is not there."""
    values = document.get(name)
    return _Section(name, values if isinstance(values, dict) else {})


# --------------------------------------------------------------- the layering


def build_settings(document: dict[str, Any]) -> Settings:
    """Resolve every setting from a parsed file and the environment.

    Args:
        document: What the configuration file held, section by section.

    Returns:
        The settings, with the file overruled by the environment and both
        overruling the defaults.
    """
    return Settings(
        paths=_paths(document),
        server=_server(document),
        logging=_logs(document),
        transcription=_transcription(document),
        audio=_audio(document),
        summarization=_summarization(document),
        chat=_chat(document),
        pipeline=_pipeline(document),
        gemini_api_key=os.getenv(API_KEY_ENV) or os.getenv(FALLBACK_API_KEY_ENV),
    )


def _paths(document: dict[str, Any]) -> Paths:
    """Resolve the ``paths`` section."""
    section, fallback = _section(document, "paths"), Paths()
    return Paths(
        storage_root=section.read(
            "storage_root", "SENTRY_STORAGE_ROOT", _path, fallback.storage_root
        ),
        frontend_dist=section.read(
            "frontend_dist", "SENTRY_FRONTEND_DIST", _path, fallback.frontend_dist
        ),
        ffmpeg=section.read("ffmpeg", "SENTRY_FFMPEG", _text, fallback.ffmpeg),
        ffprobe=section.read("ffprobe", "SENTRY_FFPROBE", _text, fallback.ffprobe),
    )


def _server(document: dict[str, Any]) -> Server:
    """Resolve the ``server`` section."""
    section, fallback = _section(document, "server"), Server()
    return Server(
        host=section.read("host", "SENTRY_HOST", _text, fallback.host),
        port=section.read("port", "SENTRY_PORT", _port, fallback.port),
        cors_origins=section.read(
            "cors_origins", "SENTRY_CORS_ORIGINS", _texts, fallback.cors_origins
        ),
        max_upload_mb=section.read(
            "max_upload_mb", "SENTRY_MAX_UPLOAD_MB", _positive, fallback.max_upload_mb
        ),
    )


def _logs(document: dict[str, Any]) -> Logs:
    """Resolve the ``logging`` section."""
    section, fallback = _section(document, "logging"), Logs()
    return Logs(level=section.read("level", "SENTRY_LOG_LEVEL", _level, fallback.level))


def _transcription(document: dict[str, Any]) -> Transcription:
    """Resolve the ``transcription`` section."""
    section, fallback = _section(document, "transcription"), Transcription()
    return Transcription(
        model=section.read(
            "model", "SENTRY_TRANSCRIPTION_MODEL", _text, fallback.model
        ),
        language=section.read(
            "language", "SENTRY_TRANSCRIPTION_LANGUAGE", _text, fallback.language
        ),
        chunk_minutes=section.read(
            "chunk_minutes",
            "SENTRY_TRANSCRIPTION_CHUNK_MINUTES",
            _positive,
            fallback.chunk_minutes,
        ),
        context_seconds=section.read(
            "context_seconds",
            "SENTRY_TRANSCRIPTION_CONTEXT_SECONDS",
            _number,
            fallback.context_seconds,
        ),
        max_inline_mb=section.read(
            "max_inline_mb",
            "SENTRY_TRANSCRIPTION_MAX_INLINE_MB",
            _positive,
            fallback.max_inline_mb,
        ),
        timeout_seconds=section.read(
            "timeout_seconds",
            "SENTRY_TRANSCRIPTION_TIMEOUT",
            _positive,
            fallback.timeout_seconds,
        ),
        attempts=section.read(
            "attempts", "SENTRY_TRANSCRIPTION_ATTEMPTS", _count, fallback.attempts
        ),
        max_output_tokens=section.read(
            "max_output_tokens",
            "SENTRY_TRANSCRIPTION_MAX_OUTPUT_TOKENS",
            _count,
            fallback.max_output_tokens,
        ),
    )


def _audio(document: dict[str, Any]) -> Audio:
    """Resolve the ``audio`` section."""
    section, fallback = _section(document, "audio"), Audio()
    return Audio(
        sample_rate=section.read(
            "sample_rate", "SENTRY_AUDIO_SAMPLE_RATE", _count, fallback.sample_rate
        ),
        encodings=section.read(
            "encodings", "SENTRY_AUDIO_ENCODINGS", _texts, fallback.encodings
        ),
        opus_bitrate=section.read(
            "opus_bitrate", "SENTRY_AUDIO_OPUS_BITRATE", _text, fallback.opus_bitrate
        ),
    )


def _summarization(document: dict[str, Any]) -> Summarization:
    """Resolve the ``summarization`` section."""
    section, fallback = _section(document, "summarization"), Summarization()
    return Summarization(
        model=section.read("model", "SENTRY_SUMMARY_MODEL", _text, fallback.model),
        temperature=section.read(
            "temperature", "SENTRY_SUMMARY_TEMPERATURE", _number, fallback.temperature
        ),
        max_characters=section.read(
            "max_characters",
            "SENTRY_SUMMARY_MAX_CHARACTERS",
            _count,
            fallback.max_characters,
        ),
        max_output_tokens=section.read(
            "max_output_tokens",
            "SENTRY_SUMMARY_MAX_OUTPUT_TOKENS",
            _count,
            fallback.max_output_tokens,
        ),
    )


def _chat(document: dict[str, Any]) -> Chat:
    """Resolve the ``chat`` section."""
    section, fallback = _section(document, "chat"), Chat()
    return Chat(
        model=section.read("model", "SENTRY_CHAT_MODEL", _text, fallback.model),
        temperature=section.read(
            "temperature", "SENTRY_CHAT_TEMPERATURE", _number, fallback.temperature
        ),
        max_characters=section.read(
            "max_characters",
            "SENTRY_CHAT_MAX_CHARACTERS",
            _count,
            fallback.max_characters,
        ),
        max_output_tokens=section.read(
            "max_output_tokens",
            "SENTRY_CHAT_MAX_OUTPUT_TOKENS",
            _count,
            fallback.max_output_tokens,
        ),
        max_source_mb=section.read(
            "max_source_mb",
            "SENTRY_CHAT_MAX_SOURCE_MB",
            _positive,
            fallback.max_source_mb,
        ),
    )


def _pipeline(document: dict[str, Any]) -> Pipeline:
    """Resolve the ``pipeline`` section."""
    section, fallback = _section(document, "pipeline"), Pipeline()
    return Pipeline(
        auto_process_on_upload=section.read(
            "auto_process_on_upload",
            "SENTRY_AUTO_PROCESS",
            _flag,
            fallback.auto_process_on_upload,
        )
    )


# ---------------------------------------------------------------- the values


def _text(raw: Any) -> str:
    """Read a value as a non-empty piece of text."""
    value = str(raw).strip()
    if not value:
        raise ValueError("it is empty")
    return value


def _texts(raw: Any) -> tuple[str, ...]:
    """Read a value as a list, written as a YAML list or comma separated."""
    entries = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    values = tuple(str(entry).strip() for entry in entries if str(entry).strip())
    if not values:
        raise ValueError("it holds nothing")
    return values


def _path(raw: Any) -> Path:
    """Read a value as a path, with ``~`` expanded."""
    return Path(_text(raw)).expanduser()


def _number(raw: Any) -> float:
    """Read a value as a number that is not negative."""
    value = float(_text(raw))
    if value < 0:
        raise ValueError(f"{value} is negative")
    return value


def _positive(raw: Any) -> float:
    """Read a value as a number greater than zero."""
    value = float(_text(raw))
    if value <= 0:
        raise ValueError(f"{value} is not greater than zero")
    return value


def _count(raw: Any) -> int:
    """Read a value as a whole number greater than zero."""
    value = float(_text(raw))
    if value <= 0 or value != int(value):
        raise ValueError(f"{raw!r} is not a whole number greater than zero")
    return int(value)


def _port(raw: Any) -> int:
    """Read a value as a port number."""
    value = _count(raw)
    if value > 65535:
        raise ValueError(f"{value} is not a port")
    return value


def _flag(raw: Any) -> bool:
    """Read a value as a yes or a no."""
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{raw!r} is neither true nor false")


def _level(raw: Any) -> str:
    """Read a value as a logging level."""
    value = _text(raw).upper()
    if value not in logging.getLevelNamesMapping():
        raise ValueError(f"{raw!r} is not a logging level")
    return value


# ------------------------------------------------------------------- loading


def load_settings() -> Settings:
    """Assemble the environment and the file, and resolve everything once.

    Returns:
        The settings the process runs on.

    Raises:
        ConfigError: If a configuration file is named or present and cannot
            be used.
    """
    env_file = load_environment()
    config_file, document = load_config_file()

    resolved = build_settings(document)
    return Settings(
        paths=resolved.paths,
        server=resolved.server,
        logging=resolved.logging,
        transcription=resolved.transcription,
        audio=resolved.audio,
        summarization=resolved.summarization,
        chat=resolved.chat,
        pipeline=resolved.pipeline,
        gemini_api_key=resolved.gemini_api_key,
        config_file=config_file,
        env_file=env_file,
    )


settings: Settings = load_settings()
"""What the whole process runs on, resolved when this module was imported."""

ENV_FILE: Path | None = settings.env_file
"""The ``.env`` that was read at import, or ``None`` if there was none."""

CONFIG_FILE: Path | None = settings.config_file
"""The ``sentry.yml`` that was read at import, or ``None`` if there was none."""
