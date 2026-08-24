"""Endpoints of the ``/prompts`` resource.

The pipeline is steered by two system prompts, one per step, and both can be
rewritten from the settings dialog. What travels here is only their text: the
catalogue itself — which prompts exist, what each step does with one — lives
in :mod:`core.prompts` and is not the client's to change.

A rewrite is stored as an override, so a delete is a reset: the default goes
back in charge, and it is the one shipped with the code rather than a copy
frozen at the moment somebody first opened the editor.
"""

from fastapi import APIRouter, HTTPException, status

from api.dependencies import Memory
from api.schemas import PromptOut, PromptUpdate
from core import (
    PROMPTS,
    Prompt,
    UnknownPrompt,
    get_prompt,
    prompt_text,
    reset_prompt,
    save_prompt,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get(
    "",
    response_model=list[PromptOut],
    summary="List the prompts",
)
def list_prompts(memory: Memory) -> list[PromptOut]:
    """List every prompt of the pipeline, in the order the steps run them.

    Args:
        memory: Storage the rewrites are read from.

    Returns:
        The prompts, each carrying the text in force and the default.
    """
    return [
        PromptOut.from_prompt(prompt, text=prompt_text(memory, prompt.id))
        for prompt in PROMPTS
    ]


@router.get(
    "/{prompt_id}",
    response_model=PromptOut,
    summary="Read a prompt",
)
def read_prompt(memory: Memory, prompt_id: str) -> PromptOut:
    """Return one prompt, as the next run would use it.

    Raises:
        HTTPException: 404 if no prompt carries that id.
    """
    prompt = _catalogued(prompt_id)
    return PromptOut.from_prompt(prompt, text=prompt_text(memory, prompt.id))


@router.put(
    "/{prompt_id}",
    response_model=PromptOut,
    summary="Rewrite a prompt",
)
def update_prompt(memory: Memory, prompt_id: str, payload: PromptUpdate) -> PromptOut:
    """Replace the text of a prompt, for every run from the next one on.

    Nothing already processed is touched: a transcript keeps the words it was
    written with, and only a recording run again is steered by the new text.

    Args:
        memory: Storage the rewrite is written to.
        prompt_id: Prompt to rewrite.
        payload: The new text.

    Returns:
        The prompt as it now stands.

    Raises:
        HTTPException: 404 if no prompt carries that id, 400 if the text holds
            nothing but blank space.
    """
    prompt = _catalogued(prompt_id)
    try:
        text = save_prompt(memory, prompt.id, payload.text)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return PromptOut.from_prompt(prompt, text=text)


@router.delete(
    "/{prompt_id}",
    response_model=PromptOut,
    summary="Restore the default of a prompt",
)
def restore_prompt(memory: Memory, prompt_id: str) -> PromptOut:
    """Drop the rewrite of a prompt, putting the shipped default back.

    The default travels back in the answer rather than a 204: the editor that
    asked for the reset is showing the old text and needs the new one.

    Raises:
        HTTPException: 404 if no prompt carries that id.
    """
    prompt = _catalogued(prompt_id)
    return PromptOut.from_prompt(prompt, text=reset_prompt(memory, prompt.id))


def _catalogued(prompt_id: str) -> Prompt:
    """Return the catalogue entry, turning an unknown id into a 404."""
    try:
        return get_prompt(prompt_id)
    except UnknownPrompt as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
