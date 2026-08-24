<script setup lang="ts">
/**
 * The row a new folder is named in.
 *
 * It stands where the folder itself will stand, so the tree never jumps: the
 * name is typed in place, and the folder exists as soon as it is committed.
 */
import { onMounted, ref } from "vue";

import { indent } from "@/components/sidebar";
import { useLibrary } from "@/composables/useLibrary";

const props = defineProps<{ depth: number }>();

const { drafting, commitDraft, cancelDraft } = useLibrary();

const name = ref("");
const field = ref<HTMLInputElement | null>(null);

onMounted(() => field.value?.focus());
</script>

<template>
  <li>
    <div
      class="row row--folder row--draft"
      :style="{ paddingLeft: indent(props.depth) }"
    >
      <span class="chevron">›</span>
      <input
        ref="field"
        v-model="name"
        class="field"
        type="text"
        placeholder="Folder name"
        spellcheck="false"
        :disabled="drafting"
        aria-label="Name of the new folder"
        @contextmenu.stop
        @keydown.enter.prevent="commitDraft(name)"
        @keydown.esc.prevent="cancelDraft()"
        @blur="commitDraft(name)"
      />
    </div>
  </li>
</template>

<style scoped>
.row--draft,
.row--draft:hover {
  background: none;
  cursor: default;
}
</style>
