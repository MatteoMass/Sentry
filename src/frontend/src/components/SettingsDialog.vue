<script setup lang="ts">
/**
 * The settings dialog, opened from the gear in the sidebar header.
 *
 * It is a native modal, like the one standing in front of a delete, so the
 * browser takes care of the top layer and of the focus. Escape is caught
 * rather than left alone: leaving is a step the dialog may have to ask about
 * first, when a prompt was rewritten and not yet stored.
 *
 * One screen is drawn at a time — the sections, the prompts, one prompt —
 * because that is how the state reads it, and the header only offers a way
 * back when there is somewhere to go back to.
 */
import { nextTick, ref, watch } from "vue";

import { SECTIONS, useSettings } from "@/composables/useSettings";

const {
  open,
  view,
  prompts,
  loading,
  error,
  saving,
  draft,
  editing,
  edited,
  close,
  openSection,
  openPrompt,
  back,
  save,
  reset,
  revert,
} = useSettings();

const dialog = ref<HTMLDialogElement | null>(null);

watch(open, async (opened) => {
  // The element only exists while the dialog is open, so it is shown after
  // the render that put it there.
  await nextTick();
  if (opened) {
    dialog.value?.showModal();
  } else {
    dialog.value?.close();
  }
});

/** What the header calls the screen the dialog is on. */
function title(): string {
  if (view.value.kind === "prompt") {
    return editing.value?.title ?? "Prompt";
  }
  return view.value.kind === "prompts" ? "Prompts" : "Settings";
}
</script>

<template>
  <Teleport to="body">
    <dialog
      v-if="open"
      ref="dialog"
      class="dialog"
      aria-label="Settings"
      @cancel.prevent="close"
    >
      <header class="head">
        <button
          v-if="view.kind !== 'sections'"
          class="icon"
          title="Back"
          type="button"
          @click="back"
        >
          ‹
        </button>
        <h2 class="title">{{ title() }}</h2>
        <button class="icon" title="Close" type="button" @click="close">×</button>
      </header>

      <p v-if="error" class="notice">{{ error }}</p>

      <div class="body">
        <!-- What settings there are. Only the prompts have a screen so far. -->
        <ul v-if="view.kind === 'sections'" class="list">
          <li v-for="section in SECTIONS" :key="section.id">
            <button class="entry" type="button" @click="openSection(section)">
              <span class="entry-text">
                <span class="entry-title">{{ section.title }}</span>
                <span class="entry-body muted">{{ section.description }}</span>
              </span>
              <span class="chevron" aria-hidden="true">›</span>
            </button>
          </li>
        </ul>

        <!-- The prompts of the pipeline, in the order the steps run them. -->
        <template v-else-if="view.kind === 'prompts'">
          <p v-if="loading && !prompts.length" class="state muted">Loading…</p>
          <ul v-else class="list">
            <li v-for="prompt in prompts" :key="prompt.id">
              <button class="entry" type="button" @click="openPrompt(prompt.id)">
                <span class="entry-text">
                  <span class="entry-title">
                    {{ prompt.title }}
                    <span v-if="prompt.customized" class="badge">edited</span>
                  </span>
                  <span class="entry-body muted">{{ prompt.description }}</span>
                </span>
                <span class="chevron" aria-hidden="true">›</span>
              </button>
            </li>
          </ul>
        </template>

        <!-- One prompt, as the next run would read it. -->
        <template v-else-if="editing !== null">
          <p class="state muted">{{ editing.description }}</p>
          <textarea
            v-model="draft"
            class="editor"
            spellcheck="false"
            :disabled="saving"
            aria-label="Prompt"
          ></textarea>
          <p class="state muted">
            A rewrite steers every run from the next one on. What was already
            transcribed or summarised is left as it is.
          </p>
        </template>
      </div>

      <footer v-if="view.kind === 'prompt' && editing !== null" class="foot">
        <button
          class="button"
          type="button"
          :disabled="saving || !editing.customized"
          @click="reset"
        >
          Restore default
        </button>
        <span class="spacer"></span>
        <button
          class="button"
          type="button"
          :disabled="saving || !edited"
          @click="revert"
        >
          Undo
        </button>
        <button
          class="button button--go"
          type="button"
          :disabled="saving || !edited"
          @click="save"
        >
          {{ saving ? "Saving…" : "Save" }}
        </button>
      </footer>
    </dialog>
  </Teleport>
</template>

<style scoped>
.dialog {
  display: flex;
  flex-direction: column;
  width: min(44rem, calc(100vw - 2rem));
  max-height: min(40rem, calc(100vh - 4rem));
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 18px 50px rgb(0 0 0 / 25%);
}

.dialog::backdrop {
  background: rgb(0 0 0 / 40%);
}

.head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.8rem 1rem;
  border-bottom: 1px solid var(--border);
}

.title {
  flex: 1;
  margin: 0;
  font-size: 0.98rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.icon {
  flex: none;
  width: 1.6rem;
  padding: 0;
  border: 0;
  border-radius: calc(var(--radius) - 2px);
  background: none;
  font-size: 1.1rem;
  line-height: 1.6rem;
  cursor: pointer;
}

.icon:hover {
  background: var(--surface-hover);
}

.body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.6rem;
  min-height: 0;
  padding: 0.8rem 1rem;
  overflow: auto;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.entry {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  width: 100%;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: none;
  text-align: left;
  cursor: pointer;
}

.entry:hover {
  background: var(--surface-hover);
}

.entry-text {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
}

.entry-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 500;
}

.entry-body {
  font-size: 0.84rem;
}

/* Says the prompt is no longer the one that ships, without opening it. */
.badge {
  padding: 0 0.35rem;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 0.72rem;
  font-weight: 500;
}

.chevron {
  flex: none;
  color: var(--text-muted);
}

.editor {
  flex: 1;
  min-height: 16rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  color: var(--text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.82rem;
  line-height: 1.55;
  resize: vertical;
  tab-size: 2;
}

.editor:focus {
  border-color: var(--accent);
  outline: none;
}

.editor:disabled {
  opacity: 0.6;
}

.state {
  margin: 0;
  font-size: 0.84rem;
}

.notice {
  margin: 0.8rem 1rem 0;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--status-error);
  border-radius: var(--radius);
  color: var(--status-error);
  font-size: 0.82rem;
}

.foot {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.8rem 1rem;
  border-top: 1px solid var(--border);
}

.spacer {
  flex: 1;
}

.button {
  padding: 0.35rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: none;
  cursor: pointer;
}

.button:hover:not(:disabled) {
  background: var(--surface-hover);
}

.button:disabled {
  cursor: default;
  opacity: 0.5;
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
</style>
