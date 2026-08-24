/**
 * The settings dialog: whether it is open, and where inside it the user is.
 *
 * It drills down rather than showing everything at once — the sections, the
 * prompts of one of them, then one prompt open for editing — so the path is
 * held here as a single value: the header reads it to know what to call
 * itself, and going back is one step up it.
 *
 * The prompts are fetched when the dialog opens and kept afterwards: they are
 * two rows, they only change when this dialog changes them, and a reopened
 * dialog that redraws instantly is worth more than a guaranteed fresh read.
 */

import { computed, readonly, ref } from "vue";

import { ApiError, fetchPrompts, resetPrompt, savePrompt } from "@/api/client";
import type { Prompt } from "@/api/types";
import { useConfirm } from "@/composables/useConfirm";

/** One of the things the dialog offers, drawn as a row on its first screen. */
export interface Section {
  id: string;
  title: string;
  description: string;
}

/** What the dialog is showing: the sections, a list, or one prompt. */
export type View =
  | { kind: "sections" }
  | { kind: "prompts" }
  | { kind: "prompt"; id: string };

export const SECTIONS: readonly Section[] = [
  {
    id: "prompts",
    title: "Prompts",
    description: "Visualize and rewrite prompts.",
  },
];

const open = ref(false);
const view = ref<View>({ kind: "sections" });

const prompts = ref<Prompt[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

/** The text being edited, which is the prompt itself until it is touched. */
const draft = ref("");
const saving = ref(false);

/** The prompt the editor is open on, or `null` on any other screen. */
const editing = computed<Prompt | null>(() =>
  view.value.kind === "prompt" ? find(view.value.id) : null,
);

/** True while the editor holds something other than what is stored. */
const edited = computed(
  () => editing.value !== null && draft.value !== editing.value.text,
);

const { ask } = useConfirm();

function find(promptId: string): Prompt | null {
  return prompts.value.find((prompt) => prompt.id === promptId) ?? null;
}

/** Open the dialog on its first screen, and read the prompts once. */
function openSettings(): void {
  open.value = true;
  view.value = { kind: "sections" };
  error.value = null;
  void load();
}

/** Close the dialog, checking first that no edit would be thrown away. */
async function close(): Promise<void> {
  if (!(await mayLeave())) {
    return;
  }
  open.value = false;
  view.value = { kind: "sections" };
}

/** Read the prompts, unless they are already here. */
async function load(force = false): Promise<void> {
  if (loading.value || (prompts.value.length && !force)) {
    return;
  }
  loading.value = true;
  error.value = null;
  try {
    prompts.value = await fetchPrompts();
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}

/** Open one of the sections. Only the prompts have a screen so far. */
function openSection(section: Section): void {
  if (section.id === "prompts") {
    view.value = { kind: "prompts" };
    void load();
  }
}

/** Open one prompt for reading and rewriting. */
function openPrompt(promptId: string): void {
  const prompt = find(promptId);
  if (prompt === null) {
    return;
  }
  draft.value = prompt.text;
  error.value = null;
  view.value = { kind: "prompt", id: prompt.id };
}

/**
 * Go one screen up, from wherever the dialog is.
 *
 * The first screen has nothing above it, so there the back button is not
 * drawn at all and this is never called.
 */
async function back(): Promise<void> {
  if (view.value.kind === "prompt") {
    if (!(await mayLeave())) {
      return;
    }
    view.value = { kind: "prompts" };
    return;
  }
  view.value = { kind: "sections" };
}

/** Store what the editor holds, for every run from the next one on. */
async function save(): Promise<void> {
  const prompt = editing.value;
  if (prompt === null || saving.value) {
    return;
  }
  saving.value = true;
  error.value = null;
  try {
    replace(await savePrompt(prompt.id, draft.value));
  } catch (cause) {
    error.value = message(cause);
  } finally {
    saving.value = false;
  }
}

/** Put the shipped prompt back, once it is clear that is what was meant. */
async function reset(): Promise<void> {
  const prompt = editing.value;
  if (prompt === null || saving.value) {
    return;
  }
  const agreed = await ask({
    title: `Restore the default ${prompt.title.toLowerCase()} prompt?`,
    body: "What you wrote is dropped and the shipped prompt takes over.",
    confirm: "Restore",
    danger: true,
  });
  if (!agreed) {
    return;
  }

  saving.value = true;
  error.value = null;
  try {
    replace(await resetPrompt(prompt.id));
  } catch (cause) {
    error.value = message(cause);
  } finally {
    saving.value = false;
  }
}

/** Throw the edit away and show the stored prompt again. */
function revert(): void {
  if (editing.value !== null) {
    draft.value = editing.value.text;
  }
}

/** Swap a prompt for the row the backend answered with, editor included. */
function replace(stored: Prompt): void {
  prompts.value = prompts.value.map((prompt) =>
    prompt.id === stored.id ? stored : prompt,
  );
  draft.value = stored.text;
}

/** Ask before an unsaved edit is left behind; anything else leaves freely. */
async function mayLeave(): Promise<boolean> {
  if (!edited.value) {
    return true;
  }
  return ask({
    title: "Leave without saving?",
    body: "The prompt goes back to what is stored.",
    confirm: "Discard",
    danger: true,
  });
}

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : String(cause);
}

export function useSettings() {
  return {
    open: readonly(open),
    view: readonly(view),
    prompts: readonly(prompts),
    loading: readonly(loading),
    error: readonly(error),
    saving: readonly(saving),
    draft,
    editing,
    edited,
    openSettings,
    close,
    openSection,
    openPrompt,
    back,
    save,
    reset,
    revert,
  };
}
