<script setup lang="ts">
/**
 * The field a sidebar row turns into while it is being renamed.
 *
 * It stands exactly where the row stood, so the tree never jumps and what is
 * being renamed is never in doubt. The name is committed on Enter and on the
 * way out, and dropped on Escape — what a file manager does, and what the row
 * a new folder is named in already does next to it.
 */
import { onMounted, ref } from "vue";

import { useLibrary } from "@/composables/useLibrary";

const props = defineProps<{ current: string; label: string }>();

const { savingName, commitRename, cancelRename } = useLibrary();

const name = ref(props.current);
const field = ref<HTMLInputElement | null>(null);

onMounted(() => {
  field.value?.focus();
  // The whole name is taken: replacing it is the common case, and what is
  // kept can still be clicked back into.
  field.value?.select();
});

/**
 * Commit on Enter, drop on Escape, and keep the rest to itself.
 *
 * The row underneath answers Enter and Space with a selection or a folder
 * that opens; nothing typed in here is its business, so no key is let
 * through.
 */
function onKeyDown(event: KeyboardEvent): void {
  event.stopPropagation();
  if (event.key === "Enter") {
    event.preventDefault();
    void commitRename(name.value);
  } else if (event.key === "Escape") {
    event.preventDefault();
    cancelRename();
  }
}
</script>

<template>
  <input
    ref="field"
    v-model="name"
    class="field"
    type="text"
    spellcheck="false"
    :disabled="savingName"
    :aria-label="props.label"
    @click.stop
    @contextmenu.stop
    @keydown="onKeyDown"
    @blur="commitRename(name)"
  />
</template>
