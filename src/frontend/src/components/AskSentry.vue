<script setup lang="ts">
/**
 * The tab that asks rather than reads.
 *
 * The transcript answers everything and says nothing: what somebody actually
 * wants from an hour of talk is usually one sentence, and finding it by
 * reading is the work this tab exists to skip. A question goes to the model
 * with the recording behind it, and the answer comes back next to the player.
 *
 * What the recording contributes is the asker's to choose, because it is what
 * the call costs: the summary is a page, the transcript is a book, and the
 * source is the whole hour of audio re-encoded and uploaded again on every
 * single turn. That last one is therefore off, and turning it on is a
 * question of its own.
 *
 * Nothing is stored, here or on the backend. The conversation lives in this
 * component and travels whole with every question, so leaving the tab is what
 * ends it — which is the honest behaviour for something nobody is paying to
 * keep.
 *
 * What Sentry answers under is not edited here. The prompt is one of the
 * three the settings dialog holds, and it belongs with them: it steers every
 * conversation about every recording, and a switch that wide does not live
 * inside one of them.
 */
import { computed, nextTick, ref, watch } from "vue";

import { ApiError, askSentry } from "@/api/client";
import type { ChatContext, ChatRole, Recording } from "@/api/types";
import Markdown from "@/components/Markdown.vue";
import { useConfirm } from "@/composables/useConfirm";

const props = defineProps<{ recording: Recording }>();

const { ask } = useConfirm();

/**
 * One turn on screen.
 *
 * An answer carries what it was written by and what it was billed, which the
 * turn it belongs to is the only sensible place to say.
 */
interface Turn {
  role: ChatRole;
  content: string;
  model?: string;
  tokens?: number;
}

const turns = ref<Turn[]>([]);
const draft = ref("");
const sending = ref(false);
const error = ref<string | null>(null);

/** Where the conversation is drawn, so a new turn can be scrolled to. */
const thread = ref<HTMLElement | null>(null);

/**
 * What travels with a question.
 *
 * The first two are on because they are what makes an answer worth reading
 * and cost a fraction of what the audio costs; the third is off until
 * somebody says otherwise, and is asked about before it goes on.
 */
const context = ref<ChatContext>({ transcript: true, summary: true, source: false });

/** What each switch can actually send, which is what is stored on disk. */
const available = computed(() => ({
  transcript: props.recording.has_transcript,
  summary: props.recording.has_summary,
  source: props.recording.media_type !== null,
}));

/** What the next question will really carry: asked for, and there to send. */
const carried = computed<ChatContext>(() => ({
  transcript: context.value.transcript && available.value.transcript,
  summary: context.value.summary && available.value.summary,
  source: context.value.source && available.value.source,
}));

/** The switches, drawn in the order they cost. */
const switches = computed(() => [
  {
    id: "transcript" as const,
    label: "Transcript",
    on: context.value.transcript,
    can: available.value.transcript,
    why: available.value.transcript
      ? "Send the diarized dialogue with the question."
      : "There is no transcript stored yet.",
  },
  {
    id: "summary" as const,
    label: "Summary",
    on: context.value.summary,
    can: available.value.summary,
    why: available.value.summary
      ? "Send the stored summary with the question."
      : "There is no summary stored yet.",
  },
  {
    id: "source" as const,
    label: "Source",
    on: context.value.source,
    can: available.value.source,
    why: available.value.source
      ? "Send the recording itself as audio. This is the expensive one."
      : "No media is stored with this recording.",
  },
]);

/** True when nothing of the recording would travel with the question. */
const blind = computed(
  () =>
    !carried.value.transcript &&
    !carried.value.summary &&
    !carried.value.source,
);

/** What the whole conversation has been billed so far. */
const spent = computed(() =>
  turns.value.reduce((total, turn) => total + (turn.tokens ?? 0), 0),
);

/**
 * Ask what is in the composer.
 *
 * The question joins the conversation before it is answered, so it reads the
 * way it was typed while the model is thinking. A call that fails takes it
 * back out and puts it in the composer again: a conversation must not hold a
 * question nothing ever answered, and what was typed is worth more than the
 * failure that lost it.
 */
async function send(): Promise<void> {
  const question = draft.value.trim();
  if (question === "" || sending.value) {
    return;
  }

  const recordingId = props.recording.id;
  turns.value = [...turns.value, { role: "user", content: question }];
  draft.value = "";
  sending.value = true;
  error.value = null;

  try {
    const reply = await askSentry(recordingId, {
      messages: turns.value.map(({ role, content }) => ({ role, content })),
      ...carried.value,
    });
    if (props.recording.id !== recordingId) {
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
    if (props.recording.id !== recordingId) {
      return;
    }
    turns.value = turns.value.slice(0, -1);
    draft.value = question;
    error.value = message(cause);
  } finally {
    sending.value = false;
  }
}

/** Throw the conversation away. Nothing was stored, so nothing is lost. */
function clear(): void {
  turns.value = [];
  error.value = null;
}

/**
 * Turn one of the switches, asking first about the one that costs.
 *
 * The box is put back by hand when the question is declined: the value it is
 * bound to never changed, so nothing would redraw it.
 */
async function toggle(
  id: keyof ChatContext,
  wanted: boolean,
  box: EventTarget | null,
): Promise<void> {
  if (id !== "source" || !wanted) {
    context.value = { ...context.value, [id]: wanted };
    return;
  }

  const agreed = await ask({
    title: "Send the recording itself?",
    body:
      "The whole audio is re-encoded and uploaded with every question from" +
      " here on, and billed again each time. It is by far the most expensive" +
      " thing Sentry does — worth it for what the transcript cannot settle," +
      " and for very little else.",
    confirm: "Send it anyway",
    danger: true,
  });
  context.value = { ...context.value, source: agreed };
  if (!agreed && box instanceof HTMLInputElement) {
    box.checked = false;
  }
}

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : String(cause);
}

// A turn arriving is a turn worth seeing: the thread follows it down.
watch(
  () => turns.value.length,
  async () => {
    await nextTick();
    thread.value?.lastElementChild?.scrollIntoView({ block: "end" });
  },
);
</script>

<template>
  <div class="chat">
    <header class="chat__head">
      <div class="switches">
        <label
          v-for="entry in switches"
          :key="entry.id"
          class="switch"
          :class="{ 'switch--off': !entry.can }"
          :title="entry.why"
        >
          <input
            type="checkbox"
            :checked="entry.on"
            :disabled="!entry.can || sending"
            @change="
              toggle(
                entry.id,
                ($event.target as HTMLInputElement).checked,
                $event.target,
              )
            "
          />
          {{ entry.label }}
        </label>
      </div>

      <button
        class="icon"
        type="button"
        title="Throw the conversation away"
        :disabled="!turns.length || sending"
        @click="clear"
      >
        ⌫ Clear
      </button>
    </header>

    <div ref="thread" class="thread">
      <p v-if="!turns.length" class="muted empty">
        Ask anything about this recording — what was decided, who promised
        what, whether a name came up. Nothing here is stored: leaving this tab
        ends the conversation.
      </p>

      <div
        v-for="(turn, index) in turns"
        :key="index"
        class="turn"
        :class="`turn--${turn.role}`"
      >
        <!-- A question is drawn as it was typed; an answer comes back in the
             Markdown a model writes prose in, and is read as that. -->
        <Markdown v-if="turn.role === 'assistant'" :text="turn.content" />
        <p v-else class="turn__text">{{ turn.content }}</p>
        <p v-if="turn.model" class="muted turn__meta">
          {{ turn.model }} · {{ turn.tokens }} tokens
        </p>
      </div>

      <p v-if="sending" class="muted">Sentry is reading…</p>
    </div>

    <p v-if="error !== null" class="failure">{{ error }}</p>
    <p v-else-if="blind" class="muted warn">
      Nothing of the recording travels with the question: turn on what Sentry
      should read before asking.
    </p>

    <form class="composer" @submit.prevent="send">
      <textarea
        v-model="draft"
        class="composer__field"
        rows="3"
        :disabled="sending"
        aria-label="Question about this recording"
        placeholder="Ask Sentry about this recording…"
        @keydown.enter.exact.prevent="send"
      ></textarea>
      <div class="composer__foot">
        <span class="muted composer__state">
          {{
            spent
              ? `${spent} tokens this conversation.`
              : "Enter sends, Shift+Enter breaks the line."
          }}
        </span>
        <button
          class="button button--go"
          type="submit"
          :disabled="sending || draft.trim() === ''"
        >
          {{ sending ? "Asking…" : "Ask" }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
/* A column that fills the tab: the conversation scrolls, the two ends stay. */
.chat {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  height: 100%;
  min-height: 0;
}

.chat__head {
  display: flex;
  flex: none;
  align-items: center;
  gap: 0.4rem;
}

.switches {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  gap: 0.75rem;
  min-width: 0;
}

.switch {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  color: var(--text-muted);
  font-size: 0.82rem;
  cursor: pointer;
}

.switch--off {
  opacity: 0.45;
  cursor: default;
}

.switch input {
  accent-color: var(--accent);
  cursor: inherit;
}

/* The conversation, and the only part of the tab that moves. */
.thread {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.6rem;
  min-height: 6rem;
  overflow: auto;
  padding-right: 0.25rem;
}

.empty {
  max-width: 34rem;
  margin: auto 0;
  font-size: 0.85rem;
}

.turn {
  max-width: 90%;
  padding: 0.55rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  scroll-margin: 1rem;
}

/* The question sits to the right of the answer it asked for. */
.turn--user {
  align-self: flex-end;
  border-color: var(--accent);
  background: var(--accent-soft);
}

.turn--assistant {
  align-self: flex-start;
  background: var(--surface);
}

.turn__text {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.turn__meta {
  margin: 0.35rem 0 0;
  font-size: 0.72rem;
}

.warn {
  flex: none;
  font-size: 0.8rem;
}

.composer {
  display: flex;
  flex: none;
  flex-direction: column;
  gap: 0.5rem;
}

.composer__field {
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  font-size: 0.9rem;
  line-height: 1.55;
  resize: vertical;
}

.composer__field:focus {
  border-color: var(--accent);
  outline: none;
}

.composer__field:disabled {
  opacity: 0.6;
}

.composer__foot {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.composer__state {
  flex: 1;
  min-width: 0;
  font-size: 0.78rem;
}

.failure {
  flex: none;
  margin: 0;
  color: var(--status-error);
  font-size: 0.85rem;
}

.muted {
  margin: 0;
  color: var(--text-muted);
}

/* A button that is mostly its glyph, sitting in the header row. */
.icon {
  flex: none;
  padding: 0.25rem 0.5rem;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: none;
  color: var(--text-muted);
  font: inherit;
  font-size: 0.8rem;
  cursor: pointer;
}

.icon:hover:not(:disabled) {
  border-color: var(--border);
  background: var(--surface-hover);
  color: var(--text);
}

.icon:disabled {
  opacity: 0.45;
  cursor: default;
}

.button {
  flex: none;
  padding: 0.35rem 0.9rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: none;
  color: inherit;
  font: inherit;
  font-size: 0.85rem;
  cursor: pointer;
}

.button:hover:not(:disabled) {
  background: var(--surface-hover);
}

.button--go {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--accent-text);
}

.button--go:hover:not(:disabled) {
  opacity: 0.9;
  background: var(--accent);
}

.button:disabled {
  opacity: 0.55;
  cursor: default;
}

/* Stacked panes scroll as one page, so the thread cannot own a height. */
@media (max-width: 1100px) {
  .chat {
    height: auto;
    min-height: 28rem;
  }

  .thread {
    overflow: visible;
  }
}
</style>
