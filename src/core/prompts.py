"""The system prompts Sentry runs on, and the ones the user rewrote.

Every model call Sentry makes is steered by one system prompt, and each ships
with a default written next to the code that uses it —
:data:`core.gemini_speech.SYSTEM_PROMPT` for the transcription,
:data:`core.summarizer.SYSTEM_PROMPT` for the summary,
:data:`core.chat.SYSTEM_PROMPT` for the questions asked about a recording.
This module is the catalogue of those prompts, and the one place that knows a
user may have replaced one.

An edited prompt is stored as a setting, and only as a setting: the default
stays where it is, untouched, so resetting is a delete and an improved default
reaches every installation that never disagreed with it. Reading a prompt is
therefore "the override if there is one, the default otherwise", which is
:func:`prompt_text`, and what the pipeline calls before every run.
"""

from dataclasses import dataclass

from connectors.memory_connector import MemoryConnector
from core.chat import SYSTEM_PROMPT as CHAT_DEFAULT
from core.gemini_speech import SYSTEM_PROMPT as TRANSCRIPTION_DEFAULT
from core.summarizer import SYSTEM_PROMPT as SUMMARIZATION_DEFAULT

TRANSCRIPTION = "transcription"
SUMMARIZATION = "summarization"
CHAT = "chat"

SETTING_PREFIX = "prompt."
"""What a prompt key looks like among the other settings."""


@dataclass(frozen=True, slots=True)
class Prompt:
    """One prompt of the pipeline, as it is offered to be read and rewritten.

    Attributes:
        id: How the prompt is named over HTTP, e.g. ``'transcription'``.
        title: Name shown to whoever is editing it.
        description: What the step does with it, in one line.
        default: The prompt as it ships, which a reset goes back to.
    """

    id: str
    title: str
    description: str
    default: str

    @property
    def key(self) -> str:
        """The setting an override of this prompt is stored under."""
        return f"{SETTING_PREFIX}{self.id}"


PROMPTS: tuple[Prompt, ...] = (
    Prompt(
        id=TRANSCRIPTION,
        title="Transcription",
        description=(
            "Steers the recogniser: how the speech is written down and how"
            " the voices are told apart."
        ),
        default=TRANSCRIPTION_DEFAULT,
    ),
    Prompt(
        id=SUMMARIZATION,
        title="Summarization",
        description=(
            "Steers the summary: what is kept of a transcript, and in which"
            " sections it is reported."
        ),
        default=SUMMARIZATION_DEFAULT,
    ),
    Prompt(
        id=CHAT,
        title="Ask Sentry",
        description=(
            "Steers the chat: how a question asked about a recording is"
            " answered, and what an answer may claim."
        ),
        default=CHAT_DEFAULT,
    ),
)
"""Every prompt there is: the two steps first, in the order they run."""

_BY_ID = {prompt.id: prompt for prompt in PROMPTS}


class UnknownPrompt(LookupError):
    """Raised when a prompt is asked for by an id that names none."""


def get_prompt(prompt_id: str) -> Prompt:
    """Return the prompt named ``prompt_id``.

    Raises:
        UnknownPrompt: If no prompt carries that id.
    """
    try:
        return _BY_ID[prompt_id]
    except KeyError as error:
        raise UnknownPrompt(f"There is no prompt named {prompt_id!r}.") from error


def prompt_text(memory: MemoryConnector, prompt_id: str) -> str:
    """Return the prompt actually in force: the override, or the default.

    Args:
        memory: Storage holding the overrides.
        prompt_id: Prompt to read.

    Returns:
        The text the next run will be steered by.

    Raises:
        UnknownPrompt: If no prompt carries that id.
    """
    prompt = get_prompt(prompt_id)
    stored = memory.get_setting(prompt.key)
    return prompt.default if stored is None else stored


def prompt_is_custom(memory: MemoryConnector, prompt_id: str) -> bool:
    """Tell whether that prompt was rewritten, rather than left as it ships."""
    return memory.get_setting(get_prompt(prompt_id).key) is not None


def save_prompt(memory: MemoryConnector, prompt_id: str, value: str) -> str:
    """Store a rewritten prompt, or drop the override when it matches again.

    A text edited back into what it ships as is not an override: storing it
    would freeze today's default into the installation, and the next run would
    read the same words either way.

    Args:
        memory: Storage the override is written to.
        prompt_id: Prompt to rewrite.
        value: The new text. Surrounding blank space is trimmed.

    Returns:
        The prompt as it now stands.

    Raises:
        UnknownPrompt: If no prompt carries that id.
        ValueError: If ``value`` holds nothing but blank space.
    """
    prompt = get_prompt(prompt_id)
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("A prompt cannot be empty.")

    if cleaned == prompt.default.strip():
        memory.unset_setting(prompt.key)
        return prompt.default

    memory.set_setting(prompt.key, cleaned)
    return cleaned


def reset_prompt(memory: MemoryConnector, prompt_id: str) -> str:
    """Drop the override of a prompt and return the default it goes back to.

    Raises:
        UnknownPrompt: If no prompt carries that id.
    """
    prompt = get_prompt(prompt_id)
    memory.unset_setting(prompt.key)
    return prompt.default
