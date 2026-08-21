<script setup lang="ts">
/**
 * One recording in the sidebar: something to select, and something to carry
 * into another folder.
 */
import { computed } from "vue";

import type { Recording } from "@/api/types";
import { indent } from "@/components/sidebar";
import { useConfirm } from "@/composables/useConfirm";
import { useContextMenu } from "@/composables/useContextMenu";
import { pickMedia } from "@/composables/useFilePicker";
import { useLibrary } from "@/composables/useLibrary";

const props = defineProps<{ recording: Recording; depth: number }>();

const {
  selectedId,
  dragged,
  select,
  startDrag,
  endDrag,
  beginDraft,
  upload,
  removeRecording,
} = useLibrary();
const { open } = useContextMenu();
const { ask } = useConfirm();

const carried = computed(
  () => dragged.value?.kind === "recording" && dragged.value.id === props.recording.id,
);

function onDragStart(event: DragEvent): void {
  startDrag({ kind: "recording", id: props.recording.id });
  if (event.dataTransfer !== null) {
    event.dataTransfer.effectAllowed = "move";
    // Firefox starts no drag at all unless something is carried along.
    event.dataTransfer.setData("text/plain", props.recording.name);
  }
}

/** A right click here is about the folder holding it, as in a file manager. */
function onContextMenu(event: MouseEvent): void {
  open(event, [
    { label: "New folder", run: () => beginDraft(props.recording.folder) },
    { label: "Upload recording…", run: () => void uploadHere() },
    { label: "Delete recording…", danger: true, run: () => void confirmDelete() },
  ]);
}

/** Ask for files and file them beside this recording. */
async function uploadHere(): Promise<void> {
  await upload(await pickMedia(), props.recording.folder);
}

/** Delete the recording, media and index entry alike, once it is confirmed. */
async function confirmDelete(): Promise<void> {
  const agreed = await ask({
    title: `Delete “${props.recording.name}”?`,
    body:
      "Its media and everything the index holds about it go with it." +
      " This cannot be undone.",
    confirm: "Delete",
    danger: true,
  });

  if (agreed) {
    await removeRecording(props.recording.id);
  }
}
</script>

<template>
  <li>
    <div
      class="row row--recording"
      role="button"
      tabindex="0"
      draggable="true"
      :class="{
        'row--selected': props.recording.id === selectedId,
        'row--dragging': carried,
      }"
      :style="{ paddingLeft: indent(props.depth) }"
      :title="props.recording.name"
      @click="select(props.recording.id)"
      @keydown.enter.prevent="select(props.recording.id)"
      @keydown.space.prevent="select(props.recording.id)"
      @contextmenu="onContextMenu"
      @dragstart="onDragStart"
      @dragend="endDrag"
    >
      <span class="label">{{ props.recording.name }}</span>
    </div>
  </li>
</template>
