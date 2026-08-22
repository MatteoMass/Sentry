<script setup lang="ts">
/**
 * The centre pane: everything the API knows about the selected recording,
 * what the pipeline has made of it so far, and what can be asked for next.
 *
 * The pipeline is two steps, and this panel is built around that: a
 * transcription that succeeded is shown whatever became of the summary, and
 * what the button offers follows what is stored rather than the status alone
 * — a summary that failed is offered another summary, not another hour of
 * audio sent back to the provider.
 */
import { computed, ref, watch } from "vue";

import { ApiError, fetchSummary, fetchTranscript } from "@/api/client";
import { isRunningStatus } from "@/api/types";
import type { Recording, Summary, Transcript } from "@/api/types";
import StatusBadge from "@/components/StatusBadge.vue";
import { useLibrary } from "@/composables/useLibrary";

// `process` is a global in a browser bundle; the actions are given names of
// their own rather than shadowing it.
const {
  selected,
  selectedPath,
  process: startProcessing,
  transcribe: startTranscription,
  summarize: startSummary,
  isRunning,
} = useLibrary();

/** Something the panel offers to do, once. */
interface Action {
  label: string;
  run: () => void;
}

/** The folders leading to the recording, as one readable line. */
const location = computed(() =>
  selectedPath.value.length
    ? selectedPath.value.map((folder) => folder.name).join(" / ")
    : "Top level",
);

/** True while a step is running on it, whoever started it. */
const busy = computed(
  () =>
    selected.value !== null &&
    (isRunningStatus(selected.value.status) || isRunning(selected.value.id)),
);

/** What is running, said in the button that cannot be pressed. */
const busyLabel = computed(() => {
  switch (selected.value?.status) {
    case "transcribing":
      return "Transcribing…";
    case "summarizing":
      return "Summarising…";
    default:
      return "Working…";
  }
});

/**
 * The step worth offering, which is the one that is missing.
 *
 * Nothing here reads the status: what is on disk is what decides. A recording
 * that failed at the summary and one that was only ever transcribed are
 * offered the same thing, because the same thing is missing from both.
 */
const primary = computed<Action | null>(() => {
  const recording = selected.value;
  if (recording === null) {
    return null;
  }
  if (!recording.has_transcript) {
    return { label: "Process", run: () => void startProcessing(recording.id) };
  }
  if (!recording.has_summary) {
    return {
      label: "Generate summary",
      run: () => void startSummary(recording.id),
    };
  }
  return {
    label: "Reprocess",
    run: () => void startProcessing(recording.id, true),
  };
});

/**
 * The other thing that can be asked for, once there is a transcript.
 *
 * Sending the audio again is never the first offer: it is the expensive half,
 * and it throws away a result that has already been paid for.
 */
const secondary = computed<Action | null>(() => {
  const recording = selected.value;
  if (recording === null || !recording.has_transcript) {
    return null;
  }
  return recording.has_summary
    ? { label: "Regenerate summary", run: () => void startSummary(recording.id) }
    : {
        label: "Transcribe again",
        run: () => void startTranscription(recording.id),
      };
});

/** What the recording's own state means, in one line under the buttons. */
const hint = computed(() => {
  const recording = selected.value;
  if (recording === null) {
    return "";
  }
  switch (recording.status) {
    case "to_process":
      return "Nothing has been asked for yet: the media is stored and waiting.";
    case "transcribing":
      return "The audio is being recognised and split by speaker. This is the long half.";
    case "transcribed":
      return "The transcript is stored. Generating the summary reads it, and never sends the audio again.";
    case "summarizing":
      return "The model is reading the transcript.";
    case "processed":
      return "Transcript and summary are stored with the recording.";
    case "error":
      return recording.has_transcript
        ? "The summary failed, but the transcript survived it — it can be summarised again for the price of one model call."
        : "The transcription failed and nothing was stored. The server log says why.";
  }
});

// --------------------------------------------------------- what it produced

const transcript = ref<Transcript | null>(null);
const summary = ref<Summary | null>(null);
const loadingResults = ref(false);
const resultsError = ref<string | null>(null);

/** How many voices the diarization told apart, said in words. */
const speakers = computed(() => {
  const found = transcript.value?.speakers ?? [];
  return found.length ? found.join(", ") : "—";
});

/** The length of the transcribed audio, as `HH:MM:SS`. */
const duration = computed(() =>
  transcript.value === null ? "" : timestamp(transcript.value.duration),
);

/** Return `seconds` as `HH:MM:SS`, the way the stored transcript reads. */
function timestamp(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return [whole / 3600, (whole % 3600) / 60, whole % 60]
    .map((part) => String(Math.floor(part)).padStart(2, "0"))
    .join(":");
}

/**
 * Read back what the steps left on disk.
 *
 * Only what the flags say is there is asked for, so a recording that failed
 * at the summary costs one request and not a 404 alongside it. The id is
 * checked again on the way out: the selection can move while the answers are
 * travelling, and a late answer must not land in another recording's panel.
 */
async function load(recording: Recording | null): Promise<void> {
  if (recording === null) {
    transcript.value = null;
    summary.value = null;
    resultsError.value = null;
    return;
  }

  loadingResults.value = true;
  resultsError.value = null;
  try {
    const [dialogue, digest] = await Promise.all([
      recording.has_transcript ? fetchTranscript(recording.id) : null,
      recording.has_summary ? fetchSummary(recording.id) : null,
    ]);
    if (selected.value?.id !== recording.id) {
      return;
    }
    transcript.value = dialogue;
    summary.value = digest;
  } catch (cause) {
    if (selected.value?.id === recording.id) {
      transcript.value = null;
      summary.value = null;
      resultsError.value = cause instanceof ApiError ? cause.message : String(cause);
    }
  } finally {
    if (selected.value?.id === recording.id) {
      loadingResults.value = false;
    }
  }
}

// The status is part of the key, and not only the flags: a step that rewrites
// a result it already had leaves both flags exactly as they were, so a
// transcription redone from the audio would otherwise finish behind a panel
// still showing the transcript it replaced. Leaving a running status is the
// moment something on disk has just changed.
watch(
  () => {
    const recording = selected.value;
    return recording === null
      ? null
      : [
          recording.id,
          recording.status,
          recording.has_transcript,
          recording.has_summary,
        ].join(":");
  },
  () => void load(selected.value),
  { immediate: true },
);

const uploadedAt = computed(() => {
  const raw = selected.value?.uploaded_at;
  if (raw === undefined) {
    return "";
  }
  const moment = new Date(raw);
  return Number.isNaN(moment.getTime())
    ? raw
    : moment.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
});
</script>

<template>
  <main class="detail">
    <div v-if="selected === null" class="placeholder">
      <p>No recording selected.</p>
      <p class="muted">Pick one on the left to see its details.</p>
    </div>

    <article v-else class="content">
      <header class="head">
        <p class="location muted">{{ location }}</p>
        <h2 class="name">{{ selected.name }}</h2>
        <StatusBadge :status="selected.status" />
      </header>

      <dl class="facts">
        <div class="fact">
          <dt>Uploaded</dt>
          <dd>{{ uploadedAt }}</dd>
        </div>
        <div class="fact">
          <dt>Identifier</dt>
          <dd class="mono">{{ selected.id }}</dd>
        </div>
        <div class="fact">
          <dt>Folder</dt>
          <dd class="mono">{{ selected.folder ?? "—" }}</dd>
        </div>
      </dl>

      <section class="processing">
        <div class="processing__head">
          <h3>Processing</h3>
          <div class="actions">
            <button
              v-if="secondary !== null"
              class="button"
              type="button"
              :disabled="busy"
              @click="secondary.run()"
            >
              {{ secondary.label }}
            </button>
            <button
              class="button button--go"
              type="button"
              :disabled="busy || primary === null"
              @click="primary?.run()"
            >
              {{ busy ? busyLabel : primary?.label }}
            </button>
          </div>
        </div>

        <ol class="steps">
          <li :class="{ 'step--done': selected.has_transcript }">
            <span class="step__mark" />
            Transcript &amp; diarization
          </li>
          <li :class="{ 'step--done': selected.has_summary }">
            <span class="step__mark" />
            Summary
          </li>
        </ol>

        <p class="muted">{{ hint }}</p>
      </section>

      <p v-if="resultsError !== null" class="failure">{{ resultsError }}</p>

      <section v-if="summary !== null" class="result">
        <h3>Summary</h3>
        <p v-if="summary.overview" class="overview">{{ summary.overview }}</p>
        <template
          v-for="group in [
            { heading: 'Key points', entries: summary.key_points },
            { heading: 'Decisions', entries: summary.decisions },
            { heading: 'Actions', entries: summary.action_items },
          ]"
          :key="group.heading"
        >
          <template v-if="group.entries.length">
            <h4>{{ group.heading }}</h4>
            <ul>
              <li v-for="(entry, index) in group.entries" :key="index">{{ entry }}</li>
            </ul>
          </template>
        </template>
        <p class="muted note">Written by {{ summary.model || "the model" }}.</p>
      </section>

      <section v-if="transcript !== null" class="result">
        <h3>Transcript</h3>
        <p class="muted note">
          {{ transcript.language }} · {{ duration }} · {{ speakers }} ·
          {{ transcript.provider }}/{{ transcript.model }}
        </p>
        <div class="dialogue">
          <p
            v-for="(utterance, index) in transcript.utterances"
            :key="index"
            class="utterance"
          >
            <span class="mono time">{{ timestamp(utterance.start) }}</span>
            <span class="speaker">{{ utterance.label }}</span>
            <span>{{ utterance.text }}</span>
          </p>
          <p v-if="!transcript.utterances.length" class="muted">
            Nothing was recognised in the audio.
          </p>
        </div>
      </section>

      <p v-else-if="loadingResults" class="muted">Reading what is stored…</p>
    </article>
  </main>
</template>

<style scoped>
.detail {
  flex: 1;
  height: 100%;
  overflow: auto;
  background: var(--surface-sunken);
}

.content {
  max-width: 780px;
  margin: 0 auto;
  padding: 2rem 2.5rem;
}

.head {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.5rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--border);
}

.location {
  margin: 0;
  font-size: 0.82rem;
  letter-spacing: 0.02em;
}

.name {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1.25rem;
  margin: 1.5rem 0 0;
}

.fact dt {
  margin-bottom: 0.2rem;
  color: var(--text-muted);
  font-size: 0.78rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.fact dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.88rem;
}

.processing,
.result {
  margin-top: 2rem;
  padding: 1.25rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}

.processing__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.actions {
  display: flex;
  gap: 0.5rem;
}

.processing h3,
.result h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
}

.processing p,
.result p {
  margin: 0;
  font-size: 0.9rem;
}

/* The two steps, each carrying whether it has left something behind. */
.steps {
  display: flex;
  gap: 1.25rem;
  margin: 0.9rem 0;
  padding: 0;
  list-style: none;
  color: var(--text-muted);
  font-size: 0.85rem;
}

.steps li {
  display: flex;
  align-items: center;
  gap: 0.4em;
}

.step__mark {
  width: 0.55em;
  height: 0.55em;
  border: 1px solid currentColor;
  border-radius: 50%;
}

.step--done {
  color: var(--status-processed);
}

.step--done .step__mark {
  background: currentColor;
}

.failure {
  margin: 1rem 0 0;
  color: var(--status-error);
  font-size: 0.9rem;
}

.overview {
  margin-top: 0.75rem;
}

.result h4 {
  margin: 1rem 0 0.35rem;
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.result ul {
  margin: 0;
  padding-left: 1.1rem;
  font-size: 0.9rem;
}

.result li + li {
  margin-top: 0.25rem;
}

.note {
  margin-top: 0.75rem;
  font-size: 0.8rem;
}

/* Long enough to read, bounded enough to keep the actions in sight. */
.dialogue {
  max-height: 26rem;
  margin-top: 0.9rem;
  overflow: auto;
}

.utterance {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 0.6rem;
  align-items: baseline;
  padding: 0.35rem 0;
  border-top: 1px solid var(--border);
}

.time {
  color: var(--text-muted);
  font-size: 0.78rem;
}

.speaker {
  font-weight: 600;
  white-space: nowrap;
}

.button {
  flex: none;
  padding: 0.35rem 0.9rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: none;
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
</style>
