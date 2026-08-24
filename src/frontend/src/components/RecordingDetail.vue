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
 *
 * The recording itself is here too, in a player the transcript drives: a line
 * clicked in the dialogue is a moment in the audio, and reading one has to be
 * the same gesture as hearing it. What the whole folder holds can be taken
 * away in one archive, media and results together.
 */
import { computed, nextTick, ref, watch } from "vue";

import {
  ApiError,
  archiveUrl,
  fetchSummary,
  fetchTranscript,
  mediaUrl,
} from "@/api/client";
import { isRunningStatus } from "@/api/types";
import type { Recording, Summary, Transcript, Utterance } from "@/api/types";
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
  rename,
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

// ----------------------------------------------------------------- renaming

/**
 * The title, while it is being typed over.
 *
 * The panel keeps its own field rather than sharing the one the sidebar row
 * turns into: both call the same action, and only one of them is ever focused
 * that way.
 */
const editingName = ref(false);
const draftName = ref("");
const savingName = ref(false);
const nameField = ref<HTMLInputElement | null>(null);

async function startRename(): Promise<void> {
  const recording = selected.value;
  if (recording === null) {
    return;
  }
  draftName.value = recording.name;
  editingName.value = true;
  await nextTick();
  nameField.value?.focus();
  nameField.value?.select();
}

function cancelRename(): void {
  editingName.value = false;
}

/**
 * Take the name that was typed, unless it is empty or unchanged.
 *
 * A name the server turns down leaves the field open with what was typed
 * still in it — the sidebar says why — so it can be fixed rather than typed
 * again.
 */
async function commitRename(): Promise<void> {
  const recording = selected.value;
  if (recording === null || !editingName.value || savingName.value) {
    return;
  }

  const cleaned = draftName.value.trim();
  if (cleaned === "" || cleaned === recording.name) {
    cancelRename();
    return;
  }

  savingName.value = true;
  try {
    if (await rename("recording", recording.id, cleaned)) {
      editingName.value = false;
    }
  } finally {
    savingName.value = false;
  }
}

// ------------------------------------------------------------------- player

const player = ref<HTMLMediaElement | null>(null);

/** Where the media is now, and whether it is running, as the player says. */
const playhead = ref(0);
const playing = ref(false);
const mediaFailed = ref(false);

/**
 * True once the file has said it carries no picture.
 *
 * The stored type is a guess made from an extension, and an extension lies:
 * an audio file saved as ``.mpeg`` is announced as video and would be given
 * a player with a black rectangle where the picture is not. The file itself
 * settles it as soon as its metadata arrives.
 */
const pictureless = ref(false);

/**
 * Where playback should pick up once the metadata is in, or `null`.
 *
 * A seek asked for before the length is known is dropped by the browser, and
 * the same is true of the player that replaces this one when the picture
 * turns out not to exist — so the moment is remembered here rather than on
 * an element that may not be the one that ends up playing.
 */
const resumeAt = ref<number | null>(null);

/**
 * What there is to play, or `null` when the folder holds no media.
 *
 * A picture is what picks the element: with one the media needs a frame to
 * be drawn in, without one an audio player is the whole of it.
 */
const media = computed(() => {
  const recording = selected.value;
  if (recording === null || recording.media_type === null) {
    return null;
  }
  return {
    url: mediaUrl(recording.id),
    type: recording.media_type,
    video: recording.media_type.startsWith("video/") && !pictureless.value,
  };
});

/**
 * Play from `seconds`, which is what clicking a line of the dialogue means.
 *
 * Nothing but the metadata is loaded until this is asked for; when even that
 * has not arrived the moment is put aside and taken up by whichever player
 * loads it.
 */
function playFrom(seconds: number): void {
  const element = player.value;
  if (element === null) {
    return;
  }
  if (element.readyState === HTMLMediaElement.HAVE_NOTHING) {
    resumeAt.value = seconds;
    element.load();
    return;
  }
  resume(element, seconds);
}

/**
 * Take what the file says about itself, then start it if it was asked for.
 *
 * A video element that reports no width has nothing to show: the media type
 * was wrong, and the panel redraws itself around an audio player — the one
 * that then loads is what picks the waiting moment up.
 */
function onLoadedMetadata(event: Event): void {
  const element = event.target as HTMLMediaElement;
  if (element instanceof HTMLVideoElement && element.videoWidth === 0) {
    pictureless.value = true;
    return;
  }
  if (resumeAt.value !== null) {
    resume(element, resumeAt.value);
    resumeAt.value = null;
  }
}

function resume(element: HTMLMediaElement, seconds: number): void {
  element.currentTime = seconds;
  playhead.value = seconds;
  // A browser may refuse to start on its own; the jump is what was asked
  // for, and it has already happened.
  void element.play().catch(() => undefined);
}

/**
 * Jump to an utterance, unless the click was the end of a selection.
 *
 * The dialogue is text before it is a set of buttons: somebody highlighting a
 * sentence to copy it is not asking to hear it.
 */
function onUtterance(utterance: Utterance): void {
  if ((window.getSelection()?.toString() ?? "") !== "") {
    return;
  }
  playFrom(utterance.start);
}

/**
 * The line being spoken, or -1 when nothing is.
 *
 * The utterances are in order, so the last one that has already started is
 * the one to mark; a gap between two of them keeps the previous line lit,
 * which reads better than nothing being lit at all.
 */
const activeUtterance = computed(() => {
  const utterances = transcript.value?.utterances ?? [];
  if (media.value === null || (!playing.value && playhead.value === 0)) {
    return -1;
  }
  let found = -1;
  for (const [index, utterance] of utterances.entries()) {
    if (utterance.start > playhead.value) {
      break;
    }
    found = index;
  }
  return found;
});

// Another recording means another player and another title: whatever was
// being typed or played belonged to the one that just left the panel.
watch(
  () => selected.value?.id ?? null,
  () => {
    editingName.value = false;
    playhead.value = 0;
    playing.value = false;
    mediaFailed.value = false;
    pictureless.value = false;
    resumeAt.value = null;
  },
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

// -------------------------------------------------------------------- tabs

/** Which of the two results the right-hand pane is showing. */
type Tab = "transcript" | "summary";

const tab = ref<Tab>("transcript");

/**
 * The tab worth opening on, which is the one with something in it.
 *
 * A recording whose summary is the only thing stored opens on the summary;
 * everything else opens on the dialogue, which is the longer read and the
 * one the player is wired to.
 */
watch(
  () => selected.value?.id ?? null,
  () => {
    tab.value =
      selected.value?.has_transcript === false && selected.value.has_summary
        ? "summary"
        : "transcript";
  },
  { immediate: true },
);

</script>

<template>
  <main class="detail">
    <div v-if="selected === null" class="placeholder">
      <p>No recording selected.</p>
      <p class="muted">Pick one on the left to see its details.</p>
    </div>

    <div v-else class="split">
      <!-- The recording itself: what it is, what can be played, what can be
           asked for. It stays put while the results are read beside it. -->
      <article class="pane pane--about">
        <header class="head">
          <p class="location muted">{{ location }}</p>

          <div class="title">
            <input
              v-if="editingName"
              ref="nameField"
              v-model="draftName"
              class="name name-field"
              type="text"
              spellcheck="false"
              :disabled="savingName"
              aria-label="Name of the recording"
              @keydown.enter.prevent="commitRename"
              @keydown.esc.prevent="cancelRename"
              @blur="commitRename"
            />
            <h2 v-else class="name">{{ selected.name }}</h2>
            <button
              v-if="!editingName"
              class="icon"
              type="button"
              title="Rename"
              aria-label="Rename this recording"
              @click="startRename"
            >
              ✎
            </button>
          </div>

          <div class="title__foot">
            <StatusBadge :status="selected.status" />
            <a
              class="button"
              :href="archiveUrl(selected.id)"
              download
              title="Download the media and everything stored with it"
            >
              ⤓ Download
            </a>
          </div>
        </header>

        <section v-if="media !== null" :key="selected.id" class="player">
          <video
            v-if="media.video"
            ref="player"
            class="media"
            controls
            preload="metadata"
            :src="media.url"
            @loadedmetadata="onLoadedMetadata"
            @timeupdate="playhead = ($event.target as HTMLMediaElement).currentTime"
            @play="playing = true"
            @pause="playing = false"
            @error="mediaFailed = true"
          />
          <audio
            v-else
            ref="player"
            class="media media--audio"
            controls
            preload="metadata"
            :src="media.url"
            @loadedmetadata="onLoadedMetadata"
            @timeupdate="playhead = ($event.target as HTMLMediaElement).currentTime"
            @play="playing = true"
            @pause="playing = false"
            @error="mediaFailed = true"
          />
          <p v-if="mediaFailed" class="failure">
            The media could not be played. It is still stored, and travels with the
            download.
          </p>
          <p v-else-if="transcript !== null" class="muted note">
            Click a line of the transcript to play from there.
          </p>
        </section>

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
      </article>

      <!-- What the pipeline made of it, one result at a time. This is the
           half that scrolls. -->
      <section class="pane pane--results">
        <div class="tabs" role="tablist" aria-label="Results">
          <button
            v-for="entry in [
              { id: 'transcript' as Tab, label: 'Transcription' },
              { id: 'summary' as Tab, label: 'Summary' },
            ]"
            :key="entry.id"
            class="tab"
            :class="{ 'tab--on': tab === entry.id }"
            type="button"
            role="tab"
            :aria-selected="tab === entry.id"
            @click="tab = entry.id"
          >
            {{ entry.label }}
          </button>
        </div>

        <div class="results" role="tabpanel">
          <p v-if="resultsError !== null" class="failure">{{ resultsError }}</p>
          <p v-else-if="loadingResults" class="muted">Reading what is stored…</p>

          <template v-else-if="tab === 'transcript'">
            <template v-if="transcript !== null">
              <p class="muted note note--first">
                {{ transcript.language }} · {{ duration }} · {{ speakers }} ·
                {{ transcript.provider }}/{{ transcript.model }}
              </p>
              <div class="dialogue">
                <p
                  v-for="(utterance, index) in transcript.utterances"
                  :key="index"
                  class="utterance"
                  :class="{
                    'utterance--seekable': media !== null,
                    'utterance--active': index === activeUtterance,
                  }"
                  :role="media === null ? undefined : 'button'"
                  :tabindex="media === null ? undefined : 0"
                  :title="media === null ? undefined : 'Play from here'"
                  @click="media === null || onUtterance(utterance)"
                  @keydown.enter.prevent="media === null || onUtterance(utterance)"
                >
                  <span class="mono time">{{ timestamp(utterance.start) }}</span>
                  <span class="speaker">{{ utterance.label }}</span>
                  <span>{{ utterance.text }}</span>
                </p>
                <p v-if="!transcript.utterances.length" class="muted">
                  Nothing was recognised in the audio.
                </p>
              </div>
            </template>
            <p v-else class="muted">
              No transcript is stored yet. Processing the recording makes one.
            </p>
          </template>

          <template v-else>
            <template v-if="summary !== null">
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
                    <li v-for="(entry, index) in group.entries" :key="index">
                      {{ entry }}
                    </li>
                  </ul>
                </template>
              </template>
              <p class="muted note">Written by {{ summary.model || "the model" }}.</p>
            </template>
            <p v-else class="muted">
              No summary is stored yet. It is written from the transcript, and never
              from the audio.
            </p>
          </template>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.detail {
  flex: 1;
  height: 100%;
  min-width: 0;
  overflow: hidden;
  background: var(--surface-sunken);
}

/* Two halves that scroll apart: the recording on the left, its results on
   the right. Each carries its own overflow, so neither moves the other. */
.split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  height: 100%;
  min-height: 0;
}

.pane {
  min-width: 0;
  height: 100%;
  overflow: auto;
}

.pane--about {
  padding: 2rem 2rem 2.5rem;
  border-right: 1px solid var(--border);
}

.pane--results {
  display: flex;
  flex-direction: column;
  overflow: hidden;
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

.title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
}

.title__foot {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.name {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

/* The title, typed over where it stands. */
.name-field {
  width: 100%;
  min-width: 0;
  padding: 0 0.3rem;
  border: 1px solid var(--accent);
  border-radius: var(--radius);
  background: var(--surface);
  color: inherit;
  font-family: inherit;
  line-height: inherit;
}

.name-field:focus {
  outline: none;
}

.name-field:disabled {
  opacity: 0.6;
}

/* A button that is only its glyph, next to what it acts on. */
.icon {
  flex: none;
  padding: 0.1rem 0.4rem;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: none;
  color: var(--text-muted);
  cursor: pointer;
}

.icon:hover {
  border-color: var(--border);
  background: var(--surface-hover);
  color: var(--text);
}

/* The recording itself, above everything that was made of it. */
.player {
  margin-top: 1.5rem;
}

.media {
  display: block;
  width: 100%;
  max-height: 26rem;
  border-radius: var(--radius);
  background: #000000;
}

/* An audio player draws its own bar and needs no room for a picture. */
.media--audio {
  max-height: none;
  background: none;
}

.facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
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

.processing {
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

.processing h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
}

.processing p,
.results p {
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
  color: var(--status-error);
  font-size: 0.9rem;
}

/* The two results, named. Only one of them is under this. */
.tabs {
  display: flex;
  flex: none;
  gap: 0.25rem;
  padding: 0 1.5rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.tab {
  padding: 0.85rem 0.75rem;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--text-muted);
  font: inherit;
  font-size: 0.88rem;
  cursor: pointer;
}

.tab:hover {
  color: var(--text);
}

.tab--on,
.tab--on:hover {
  border-bottom-color: var(--accent);
  color: var(--accent);
}

/* The half that scrolls; the recording beside it does not move with it. */
.results {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 1.5rem;
}

.overview {
  margin-bottom: 0.5rem;
}

.results h4 {
  margin: 1rem 0 0.35rem;
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.results ul {
  margin: 0;
  padding-left: 1.1rem;
  font-size: 0.9rem;
}

.results li + li {
  margin-top: 0.25rem;
}

.note {
  margin-top: 0.75rem;
  font-size: 0.8rem;
}

/* The line that says where the transcript came from sits above it. */
.note--first {
  margin-top: 0;
  margin-bottom: 0.5rem;
}

.utterance {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 0.6rem;
  align-items: baseline;
  padding: 0.35rem 0.4rem;
  border-top: 1px solid var(--border);
  scroll-margin: 1rem;
}

/* Every line is a moment in the media, once there is media to play. */
.utterance--seekable {
  cursor: pointer;
}

.utterance--seekable:hover {
  background: var(--surface-hover);
}

.utterance--active,
.utterance--active:hover {
  background: var(--accent-soft);
}

.utterance--active .time,
.utterance--active .speaker {
  color: var(--accent);
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

/* The download is a link, since that is what it is; it reads as a button. */
a.button {
  color: inherit;
  font-size: 0.9rem;
  text-decoration: none;
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

/* Too narrow for two columns: the halves stack, and the page scrolls once. */
@media (max-width: 1100px) {
  .detail {
    overflow: auto;
  }

  .split {
    grid-template-columns: 1fr;
    height: auto;
  }

  .pane {
    height: auto;
    overflow: visible;
  }

  .pane--about {
    border-right: none;
    border-bottom: 1px solid var(--border);
  }

  .pane--results,
  .results {
    overflow: visible;
  }
}
</style>
