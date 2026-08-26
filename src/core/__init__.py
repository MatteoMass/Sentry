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

Both steps are steered by a system prompt, and either can be rewritten by the
user: :mod:`core.prompts` is the catalogue of those prompts and of the
overrides stored for them.

Not everything a recording carries is machine written. :mod:`core.notes` is
the other half of its folder: what somebody typed about it, and the files —
screenshots, mostly — they kept beside it.

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
from core.chat import Chat
from core.gemini_speech import GeminiSpeechToText, Voice
from core.notes import (
    ATTACHMENTS_DIR,
    NOTES_FILE,
    Attachment,
    add_attachment,
    attachment_file,
    attachment_type,
    delete_attachment,
    has_notes,
    is_note_file,
    list_attachments,
    read_note,
    write_note,
)
from core.pipeline import (
    ARTIFACTS,
    MEDIA_BASENAME,
    SUMMARY_JSON,
    SUMMARY_MARKDOWN,
    TRANSCRIPT_JSON,
    TRANSCRIPT_TEXT,
    ProcessingPipeline,
    ProcessingResult,
    media_filename,
)
from core.prompts import (
    CHAT,
    PROMPTS,
    SUMMARIZATION,
    TRANSCRIPTION,
    Prompt,
    UnknownPrompt,
    get_prompt,
    prompt_is_custom,
    prompt_text,
    reset_prompt,
    save_prompt,
)
from core.speech import SpeechToText
from core.summarizer import Summarizer
from core.types import (
    AudioError,
    ChatError,
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
    "ATTACHMENTS_DIR",
    "CHAT",
    "DEFAULT_ENCODINGS",
    "FLAC",
    "MEDIA_BASENAME",
    "NOTES_FILE",
    "OGG_OPUS",
    "PROMPTS",
    "SUMMARIZATION",
    "SUMMARY_JSON",
    "SUMMARY_MARKDOWN",
    "TRANSCRIPTION",
    "TRANSCRIPT_JSON",
    "TRANSCRIPT_TEXT",
    "Attachment",
    "AudioError",
    "Chat",
    "ChatError",
    "CoreError",
    "Encoding",
    "GeminiSpeechToText",
    "MediaNotFound",
    "PreparedAudio",
    "ProcessingPipeline",
    "ProcessingResult",
    "Prompt",
    "SpeechToText",
    "SummarizationError",
    "Summarizer",
    "Summary",
    "Transcript",
    "TranscriptionError",
    "UnknownPrompt",
    "Utterance",
    "Voice",
    "add_attachment",
    "attachment_file",
    "attachment_type",
    "delete_attachment",
    "get_prompt",
    "has_notes",
    "is_note_file",
    "list_attachments",
    "media_filename",
    "prepare_audio",
    "probe_duration",
    "prompt_is_custom",
    "prompt_text",
    "read_note",
    "reset_prompt",
    "save_prompt",
    "speaker_label",
    "split_audio",
    "write_note",
]
