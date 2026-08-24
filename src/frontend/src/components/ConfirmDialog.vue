<script setup lang="ts">
/**
 * The dialog standing in front of a delete.
 *
 * It is a native modal, so the browser takes care of the top layer, of the
 * focus, and of Escape; leaving without choosing counts as a refusal.
 */
import { nextTick, ref, watch } from "vue";

import { useConfirm } from "@/composables/useConfirm";

const { question, answer } = useConfirm();

const dialog = ref<HTMLDialogElement | null>(null);

watch(question, async (asked) => {
  if (asked === null) {
    return;
  }
  // The element is only there once the question is, so it is opened after.
  await nextTick();
  dialog.value?.showModal();
});
</script>

<template>
  <Teleport to="body">
    <dialog
      v-if="question !== null"
      ref="dialog"
      class="dialog"
      @close="answer(false)"
    >
      <h2 class="title">{{ question.title }}</h2>
      <p v-if="question.body" class="body">{{ question.body }}</p>

      <div class="buttons">
        <button autofocus class="button" type="button" @click="answer(false)">
          Cancel
        </button>
        <button
          class="button button--go"
          :class="{ 'button--danger': question.danger }"
          type="button"
          @click="answer(true)"
        >
          {{ question.confirm }}
        </button>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.dialog {
  width: min(24rem, calc(100vw - 2rem));
  padding: 1.1rem 1.2rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 18px 50px rgb(0 0 0 / 25%);
}

.dialog::backdrop {
  background: rgb(0 0 0 / 40%);
}

.title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.body {
  margin: 0.5rem 0 0;
  color: var(--text-muted);
  font-size: 0.88rem;
}

.buttons {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1.2rem;
}

.button {
  padding: 0.35rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: none;
  cursor: pointer;
}

.button:hover {
  background: var(--surface-hover);
}

.button--go {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--accent-text);
}

.button--go:hover {
  opacity: 0.9;
  background: var(--accent);
}

.button--danger,
.button--danger:hover {
  border-color: var(--status-error);
  background: var(--status-error);
  color: var(--status-error-text);
}
</style>
