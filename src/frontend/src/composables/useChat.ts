/**
 * The conversation held about one recording, and the only place it lives.
 *
 * Asking is a tab, and a tab is left: to read the line an answer quoted, to
 * write a note about it, to look at the summary it was drawn from. None of
 * that is a reason to lose the conversation, so it is kept out here rather
 * than inside the component that draws it — the tab can be closed and opened
 * as often as somebody likes, and what was asked is still on screen.
 *
 * One conversation is kept at a time, and it belongs to a recording. Opening
 * another one ends it, because a conversation is about the hour of audio it
 * was asked over and means nothing beside a different one. Clearing it ends
 * it too, and so does a reload: nothing is stored, here or on the backend,
 * which is what makes a chat free to throw away.
 *
 * The question travels from here as well. A model reading an hour of talk
 * takes its time, and somebody who asks and goes off to read the transcript
 * while it thinks should come back to an answer rather than to the question
 * they left behind.
 */

import { readonly, ref, watch } from "vue";

import { ApiError, askSentry } from "@/api/client";
import type { ChatContext, ChatRole, Recording } from "@/api/types";
import { useLibrary } from "@/composables/useLibrary";

/**
 * One turn on screen.
 *
 * An answer carries what it was written by and what it was billed, which the
 * turn it belongs to is the only sensible place to say.
 */
export interface Turn {
  role: ChatRole;
  content: string;
  model?: string;
  tokens?: number;
}

/**
 * What travels with a question until somebody says otherwise.
 *
 * The first two are on because they are what makes an answer worth reading
 * and cost a fraction of what the audio costs; the third is off, and is asked
 * about before it goes on.
 */
const DEFAULT_CONTEXT: ChatContext = {
  transcript: true,
  summary: true,
  source: false,
};

/** The recording the conversation below is about, or `null` when there is none. */
const about = ref<string | null>(null);

const turns = ref<Turn[]>([]);
const draft = ref("");
const context = ref<ChatContext>({ ...DEFAULT_CONTEXT });
const sending = ref(false);
const error = ref<string | null>(null);

/**
 * Hold the conversation for `recordingId`, ending any other one.
 *
 * It does nothing at all when the recording is the one being talked about
 * already, which is what makes leaving the tab and coming back free.
 */
function open(recordingId: string | null): void {
  if (about.value === recordingId) {
    return;
  }
  about.value = recordingId;
  turns.value = [];
  draft.value = "";
  error.value = null;
  // The switches go back to what they cost the least as: the expensive one is
  // a decision made about one recording, and never inherited by the next.
  context.value = { ...DEFAULT_CONTEXT };
}

/* What is being talked about is whatever is selected, and not whatever tab
   happens to be open: a conversation ends when its recording is left, even if
   nobody was looking at it, and picking that recording up again starts a new
   one rather than resurrecting the old. */
const { selected } = useLibrary();
watch(
  () => selected.value?.id ?? null,
  (recordingId) => open(recordingId),
  { immediate: true },
);

/** Throw the conversation away. Nothing was stored, so nothing is lost. */
function clear(): void {
  turns.value = [];
  error.value = null;
}

/** Turn one of the switches, the caller having asked whatever it costs. */
function carry(id: keyof ChatContext, on: boolean): void {
  context.value = { ...context.value, [id]: on };
}

/**
 * Ask what is in the composer, sending `carried` of the recording with it.
 *
 * The question joins the conversation before it is answered, so it reads the
 * way it was typed while the model is thinking. A call that fails takes it
 * back out and puts it in the composer again: a conversation must not hold a
 * question nothing ever answered, and what was typed is worth more than the
 * failure that lost it.
 *
 * An answer that arrives for a conversation nobody is having any more — the
 * recording changed, or it was cleared under the request — is dropped where
 * it lands.
 */
async function ask(recording: Recording, carried: ChatContext): Promise<void> {
  const question = draft.value.trim();
  if (question === "" || sending.value) {
    return;
  }

  const asked = turns.value.length;
  turns.value = [...turns.value, { role: "user", content: question }];
  draft.value = "";
  sending.value = true;
  error.value = null;

  try {
    const reply = await askSentry(recording.id, {
      messages: turns.value.map(({ role, content }) => ({ role, content })),
      ...carried,
    });
    if (!current(recording.id, asked)) {
      return;
    }
    turns.value = [
      ...turns.value,
      {
        role: "assistant",
        content: reply.text,
        model: reply.model,
        tokens: reply.input_tokens + reply.output_tokens,
      },
    ];
  } catch (cause) {
    if (!current(recording.id, asked)) {
      return;
    }
    turns.value = turns.value.slice(0, -1);
    draft.value = question;
    error.value = cause instanceof ApiError ? cause.message : String(cause);
  } finally {
    sending.value = false;
  }
}

/** True while the conversation a question was asked in is still the one held. */
function current(recordingId: string, asked: number): boolean {
  return about.value === recordingId && turns.value.length === asked + 1;
}

export function useChat() {
  return {
    turns: readonly(turns),
    draft,
    context: readonly(context),
    sending: readonly(sending),
    error: readonly(error),
    clear,
    carry,
    ask,
  };
}
