"""Business logic of Sentry: from a stored recording to what it was about.

Two things happen to a recording once it is uploaded, and they happen in this
order because the second needs the first:

1. it is transcribed and diarized, so that the words exist and each of them
   is credited to a voice — :mod:`core.gemini_speech`, which listens to the
   recording a few minutes at a time, with the audio cut and encoded by
   :mod:`core.audio`. The interface it answers to lives in
   :mod:`core.speech`, so another provider can take its place;
2. the dialogue is distilled into the points worth remembering —
   :mod:`core.summarizer`, over the generative connector of the project.

:class:`ProcessingPipeline` is what ties them to the storage, and the only
thing an entrypoint needs to know about.
"""

from core.audio import (
    DEFAULT_ENCODINGS,
    FLAC,
    OGG_OPUS,
    Encoding,
    PreparedAudio,
    prepare_audio,
    probe_duration,
    split_audio,
)
from core.gemini_speech import GeminiSpeechToText, Voice
from core.pipeline import (
    ARTIFACTS,
    SUMMARY_JSON,
    SUMMARY_MARKDOWN,
    TRANSCRIPT_JSON,
    TRANSCRIPT_TEXT,
    ProcessingPipeline,
    ProcessingResult,
)
from core.speech import SpeechToText
from core.summarizer import Summarizer
from core.types import (
    AudioError,
    CoreError,
    MediaNotFound,
    SummarizationError,
    Summary,
    Transcript,
    TranscriptionError,
    Utterance,
    speaker_label,
)

__all__ = [
    "ARTIFACTS",
    "DEFAULT_ENCODINGS",
    "FLAC",
    "OGG_OPUS",
    "SUMMARY_JSON",
    "SUMMARY_MARKDOWN",
    "TRANSCRIPT_JSON",
    "TRANSCRIPT_TEXT",
    "AudioError",
    "CoreError",
    "Encoding",
    "GeminiSpeechToText",
    "MediaNotFound",
    "PreparedAudio",
    "ProcessingPipeline",
    "ProcessingResult",
    "SpeechToText",
    "SummarizationError",
    "Summarizer",
    "Summary",
    "Transcript",
    "TranscriptionError",
    "Utterance",
    "Voice",
    "prepare_audio",
    "probe_duration",
    "speaker_label",
    "split_audio",
]
