"""Turning an uploaded media file into audio a recogniser can read.

Whatever the browser sends — an ``.mp4`` screen recording, an ``.m4a`` voice
memo, a stereo ``.wav`` — the recogniser wants one thing: a single channel,
sampled at a rate it knows, in a container it parses. So the media is never
sent as it arrived; ffmpeg re-encodes it here first, and the pipeline only
ever sees the result.

Size is the other half of the problem. The audio travels inside the request,
and a request has a ceiling. Encodings are therefore tried in order, from the
one that transcribes best to the one that fits the most audio, and the first
that fits is the one that is sent.

Length is what the ceiling really limits, which is why a recording can also be
cut into pieces here: :func:`split_audio` hands back consecutive spans of the
same media, each knowing where it starts, so a backend that transcribes them
one at a time can put the timestamps back where they belong.

ffmpeg is expected on the PATH; ``paths.ffmpeg`` and ``paths.ffprobe`` in the
configuration file — or ``SENTRY_FFMPEG`` and ``SENTRY_FFPROBE`` — point at
another build when it is not. The rate, the encodings and the bitrate of the
lossy one are configured too, and are what the defaults below are read from.
"""

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from config import settings
from core.types import AudioError

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = settings.audio.sample_rate
"""Speech is band limited, and every recognition model is trained at 16 kHz."""


@dataclass(frozen=True, slots=True)
class Encoding:
    """One way of encoding the audio, as ffmpeg and the API each name it.

    Attributes:
        name: What the encoding is called where a human reads it.
        codec: ffmpeg encoder to run.
        container: ffmpeg output format.
        mime_type: Media type the API is told to read the bytes as.
        options: Extra ffmpeg arguments, e.g. the bitrate of a lossy codec.
    """

    name: str
    codec: str
    container: str
    mime_type: str
    options: tuple[str, ...] = ()


FLAC = Encoding(
    name="FLAC", codec="flac", container="flac", mime_type="audio/flac"
)
"""Lossless: nothing of the voices is lost to the codec."""

OGG_OPUS = Encoding(
    name="Opus",
    codec="libopus",
    container="ogg",
    mime_type="audio/ogg",
    options=("-b:a", settings.audio.opus_bitrate, "-application", "voip"),
)
"""Roughly five times smaller than FLAC, and tuned for voice.

It is what a long meeting falls back to: an hour of speech still fits in a
single request, at a cost in accuracy that speech tuned Opus keeps small.
"""

ENCODINGS_BY_NAME: dict[str, Encoding] = {"flac": FLAC, "opus": OGG_OPUS}
"""What the configuration file calls each encoding."""


def _configured_encodings() -> tuple[Encoding, ...]:
    """Return the encodings to try, in the order the configuration asks for.

    A name nobody implements is dropped rather than obeyed, and a list left
    with nothing usable falls back to both encodings: the audio has to travel
    somehow, and a typo in a file is no reason for it not to.
    """
    chosen: list[Encoding] = []
    for name in settings.audio.encodings:
        encoding = ENCODINGS_BY_NAME.get(name.lower())
        if encoding is None:
            logger.warning("Ignoring unknown audio encoding %r", name)
        else:
            chosen.append(encoding)
    return tuple(chosen) or (FLAC, OGG_OPUS)


DEFAULT_ENCODINGS: tuple[Encoding, ...] = _configured_encodings()
"""Tried in this order: best transcription first, most minutes per byte last."""


@dataclass(frozen=True, slots=True)
class PreparedAudio:
    """Audio ready to be sent, and everything the request must say about it.

    Attributes:
        content: The encoded bytes.
        encoding: How they are encoded.
        sample_rate: Sampling rate they were resampled to, in hertz.
        duration: Length of the audio in seconds, ``0.0`` when unknown.
        offset: Where this audio begins inside the media it was cut from, in
            seconds. It is ``0.0`` for a whole file, and what a transcript of
            a piece has to be shifted by to be read against the recording.
    """

    content: bytes
    encoding: Encoding
    sample_rate: int
    duration: float = 0.0
    offset: float = 0.0

    @property
    def mime_type(self) -> str:
        """Media type of the payload, as an API is told to read it."""
        return self.encoding.mime_type

    def __len__(self) -> int:
        """Return the size of the payload in bytes."""
        return len(self.content)


def prepare_audio(
    source: Path | str,
    *,
    start: float = 0.0,
    length: float | None = None,
    max_bytes: int | None = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    encodings: tuple[Encoding, ...] = DEFAULT_ENCODINGS,
) -> PreparedAudio:
    """Extract the audio of a media file, small enough to be sent.

    Each encoding is tried in turn and the first one under ``max_bytes`` wins,
    so a short recording is transcribed from lossless audio while a long one
    silently degrades to Opus rather than failing.

    Args:
        source: Media file to read, audio or video.
        start: Where to begin, in seconds from the start of the media.
        length: How much to take, in seconds. ``None`` takes it to the end.
        max_bytes: Largest payload the caller can send. ``None`` accepts the
            first encoding whatever it weighs.
        sample_rate: Rate to resample to, in hertz.
        encodings: Encodings to try, in order of preference.

    Returns:
        The encoded audio and the parameters the request must declare, knowing
        where in the media it was taken from.

    Raises:
        AudioError: If ffmpeg is missing or fails, or if no encoding fits.
    """
    media = Path(source)
    if not media.is_file():
        raise AudioError(f"No such media file: {str(media)!r}")

    start = max(0.0, start)
    total = probe_duration(media)
    duration = _span(total, start, length)
    attempts: list[str] = []

    for encoding in encodings:
        content = _encode(media, encoding, sample_rate, start=start, length=length)
        if max_bytes is None or len(content) <= max_bytes:
            return PreparedAudio(
                content=content,
                encoding=encoding,
                sample_rate=sample_rate,
                duration=duration,
                offset=start,
            )
        attempts.append(f"{encoding.name} {len(content) / 1_048_576:.1f} MiB")

    raise AudioError(
        "The audio does not fit in a single request "
        f"(limit {max_bytes} bytes, tried: {', '.join(attempts)}). "
        "Transcribe it in shorter pieces."
    )


def split_audio(
    source: Path | str,
    *,
    chunk_seconds: float,
    max_bytes: int | None = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    encodings: tuple[Encoding, ...] = DEFAULT_ENCODINGS,
) -> list[PreparedAudio]:
    """Cut the audio of a media file into consecutive pieces.

    The pieces do not overlap and none is dropped: read in order, they are the
    recording. Each carries the offset it starts at, which is what lets a
    backend transcribing them one at a time report timestamps against the
    recording rather than against the piece.

    A file shorter than one piece comes back as a single piece, so a caller
    never has to ask whether splitting was worth it.

    Args:
        source: Media file to read, audio or video.
        chunk_seconds: Length of each piece, in seconds.
        max_bytes: Largest payload the caller can send, applied per piece.
        sample_rate: Rate to resample to, in hertz.
        encodings: Encodings to try, in order of preference.

    Returns:
        The pieces, in chronological order.

    Raises:
        AudioError: If ffmpeg is missing or fails, if a piece fits in no
            encoding, or if ``chunk_seconds`` is not a positive number.
    """
    if chunk_seconds <= 0:
        raise AudioError(f"A chunk cannot last {chunk_seconds} seconds.")

    media = Path(source)
    if not media.is_file():
        raise AudioError(f"No such media file: {str(media)!r}")

    total = probe_duration(media)
    if total <= 0.0:
        # ffprobe said nothing, so there is no length to cut against; the file
        # travels whole and the ceiling is what has to hold it.
        return [
            prepare_audio(
                media,
                max_bytes=max_bytes,
                sample_rate=sample_rate,
                encodings=encodings,
            )
        ]

    starts = _starts(total, chunk_seconds)
    return [
        prepare_audio(
            media,
            start=start,
            # The last piece runs to the end whatever that costs it: a
            # remainder too short for a request of its own was folded into it,
            # and nothing may be left outside the pieces.
            length=None if index == len(starts) - 1 else chunk_seconds,
            max_bytes=max_bytes,
            sample_rate=sample_rate,
            encodings=encodings,
        )
        for index, start in enumerate(starts)
    ]


def probe_duration(source: Path | str) -> float:
    """Return the length of a media file in seconds.

    Args:
        source: Media file to inspect.

    Returns:
        The duration, or ``0.0`` when ffprobe is missing or says nothing —
        it is shown to a human and never gates the pipeline, so a failure
        here is not worth refusing the whole recording over.
    """
    ffprobe = _binary(settings.paths.ffprobe, "ffprobe")
    if ffprobe is None:
        return 0.0

    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(source),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(completed.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, OSError):
        return 0.0


def _encode(
    source: Path,
    encoding: Encoding,
    sample_rate: int,
    *,
    start: float = 0.0,
    length: float | None = None,
) -> bytes:
    """Re-encode a media file, or a span of it, to mono audio.

    The result lands in a temporary file rather than on a pipe: ffmpeg writes
    some containers by seeking back to their header, which a pipe cannot do.

    ``-ss`` goes before the input so that ffmpeg seeks rather than decodes its
    way to the span, which is what keeps cutting a two hour file into pieces
    from costing two hours of decoding per piece.

    Raises:
        AudioError: If ffmpeg is missing, fails, or produces nothing.
    """
    ffmpeg = _binary(settings.paths.ffmpeg, "ffmpeg")
    if ffmpeg is None:
        raise AudioError(
            "ffmpeg not found: install it, or point `paths.ffmpeg` "
            "(SENTRY_FFMPEG) at the executable."
        )

    with tempfile.TemporaryDirectory(prefix="sentry-audio-") as workspace:
        target = Path(workspace) / f"audio.{encoding.container}"
        command = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            *(("-ss", f"{start:.3f}") if start > 0 else ()),
            "-i", str(source),
            *(("-t", f"{length:.3f}") if length is not None else ()),
            "-vn",
            "-map", "a:0",
            "-ac", "1",
            "-ar", str(sample_rate),
            "-c:a", encoding.codec,
            *encoding.options,
            "-f", encoding.container,
            str(target),
        ]

        try:
            completed = subprocess.run(command, capture_output=True, text=True)
        except OSError as error:
            raise AudioError(f"ffmpeg could not be run: {error}") from error

        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()
            raise AudioError(
                f"ffmpeg failed on {source.name!r} "
                f"({encoding.name}): {detail[-1] if detail else 'no output'}"
            )

        content = target.read_bytes()

    if not content:
        raise AudioError(f"No audio track in {source.name!r}.")
    return content


def _span(total: float, start: float, length: float | None) -> float:
    """Return how much audio a span actually holds, as far as ffprobe knows."""
    if total <= 0.0:
        return 0.0 if length is None else max(0.0, length)
    remaining = max(0.0, total - start)
    return remaining if length is None else min(length, remaining)


def _starts(total: float, chunk_seconds: float) -> list[float]:
    """Return where each piece begins, covering ``total`` exactly once.

    A last piece worth a second of audio is not worth a request of its own, so
    a remainder shorter than a twentieth of a piece is left to the one before
    it — which then runs slightly long, and reads as one thought rather than
    two.
    """
    if total <= chunk_seconds:
        return [0.0]

    count = int(total // chunk_seconds)
    if total - count * chunk_seconds > chunk_seconds / 20:
        count += 1
    return [index * chunk_seconds for index in range(count)]


def _binary(configured: str | None, default: str) -> str | None:
    """Return the executable to run, honouring what the settings point at.

    A configured path is taken as it is written, so a build outside the PATH
    can be named in full; without one the PATH is searched.
    """
    if configured:
        return configured
    return shutil.which(default)
