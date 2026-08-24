<script setup lang="ts">
/**
 * One folder of the sidebar and everything it holds.
 *
 * The component renders itself for the levels below, so the tree can be as
 * deep as the user made it.
 *
 * The whole node, not just its row, is what a drop lands on: releasing over
 * the empty space beside what a folder holds files the item into that folder,
 * while the rows nested inside answer for themselves first.
 */
import { computed, onBeforeUnmount, watch } from "vue";

import FolderDraft from "@/components/FolderDraft.vue";
import RecordingRow from "@/components/RecordingRow.vue";
import RenameField from "@/components/RenameField.vue";
import { describe, HOVER_OPEN_MS, indent } from "@/components/sidebar";
import { useConfirm } from "@/composables/useConfirm";
import { useContextMenu } from "@/composables/useContextMenu";
import { pickMedia } from "@/composables/useFilePicker";
import type { TreeNode as Node } from "@/composables/useLibrary";
import { useLibrary } from "@/composables/useLibrary";

const props = defineProps<{ node: Node; depth: number }>();

const {
  dragged,
  toggle,
  isOpen,
  expand,
  beginDraft,
  isDrafting,
  beginRename,
  isRenaming,
  upload,
  startDrag,
  endDrag,
  markTarget,
  clearTarget,
  isTarget,
  canDropInto,
  dropInto,
  contents,
  removeFolder,
} = useLibrary();
const { open } = useContextMenu();
const { ask } = useConfirm();

const id = computed(() => props.node.folder!.id);

const carried = computed(
  () => dragged.value?.kind === "folder" && dragged.value.id === id.value,
);

/** True while a drop released here would land in this folder. */
const highlighted = computed(() => isTarget(id.value));

const empty = computed(
  () =>
    !props.node.children.length &&
    !props.node.recordings.length &&
    !isDrafting(id.value),
);

// A folder held over long enough opens, so a drop can go into a branch that
// was closed when the drag started.
let opening: number | undefined;

watch(highlighted, (over) => {
  window.clearTimeout(opening);
  if (over && !isOpen(id.value)) {
    opening = window.setTimeout(() => expand(id.value), HOVER_OPEN_MS);
  }
});

onBeforeUnmount(() => window.clearTimeout(opening));

function onDragStart(event: DragEvent): void {
  startDrag({ kind: "folder", id: id.value });
  if (event.dataTransfer !== null) {
    event.dataTransfer.effectAllowed = "move";
    // Firefox starts no drag at all unless something is carried along.
    event.dataTransfer.setData("text/plain", props.node.folder!.name);
  }
}

/**
 * Claim the drop, or refuse it.
 *
 * The event is stopped either way: this folder covers the area, so what sits
 * behind it must not catch a release the folder itself turned down.
 */
function onDragOver(event: DragEvent): void {
  if (dragged.value === null) {
    return;
  }
  event.stopPropagation();

  if (!canDropInto(id.value)) {
    clearTarget(id.value);
    return;
  }
  // Only a prevented dragover makes an element a drop target at all.
  event.preventDefault();
  if (event.dataTransfer !== null) {
    event.dataTransfer.dropEffect = "move";
  }
  markTarget(id.value);
}

function onDrop(event: DragEvent): void {
  if (dragged.value === null) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  void dropInto(id.value);
}

function onContextMenu(event: MouseEvent): void {
  open(event, [
    { label: "Rename", run: () => beginRename("folder", id.value) },
    { label: "New folder inside", run: () => beginDraft(id.value) },
    { label: "Upload recording here…", run: () => void uploadHere() },
    { label: "Delete folder…", danger: true, run: () => void confirmDelete() },
  ]);
}

/** Ask for files and file them in this folder. */
async function uploadHere(): Promise<void> {
  await upload(await pickMedia(), id.value);
}

/**
 * Delete the folder, once it is clear what goes with it.
 *
 * What it holds decides the question, and the question decides the delete: a
 * folder with something below it can only go recursively, so that is what is
 * spelled out and what is asked for.
 */
async function confirmDelete(): Promise<void> {
  const { folders, recordings } = contents(id.value);
  const held = describe(folders, recordings);
  const name = props.node.folder!.name;

  const agreed = await ask({
    title: `Delete “${name}”?`,
    body: held
      ? `${held} inside it will be deleted as well, media included. This cannot be undone.`
      : "This cannot be undone.",
    confirm: "Delete",
    danger: true,
  });

  if (agreed) {
    await removeFolder(id.value, held !== "");
  }
}
</script>

<template>
  <li
    class="node"
    @dragover="onDragOver"
    @dragleave="clearTarget(id)"
    @drop="onDrop"
  >
    <div
      class="row row--folder"
      role="button"
      tabindex="0"
      :draggable="!isRenaming('folder', id)"
      :class="{ 'row--drop': highlighted, 'row--dragging': carried }"
      :style="{ paddingLeft: indent(props.depth) }"
      :aria-expanded="isOpen(id)"
      :title="props.node.folder!.name"
      @click="toggle(id)"
      @keydown.enter.prevent="toggle(id)"
      @keydown.space.prevent="toggle(id)"
      @contextmenu="onContextMenu"
      @dragstart="onDragStart"
      @dragend="endDrag"
    >
      <span class="chevron" :class="{ 'chevron--open': isOpen(id) }">›</span>
      <RenameField
        v-if="isRenaming('folder', id)"
        :current="props.node.folder!.name"
        label="Name of the folder"
      />
      <span v-else class="label">{{ props.node.folder!.name }}</span>
      <span v-if="props.node.recordings.length" class="count">
        {{ props.node.recordings.length }}
      </span>
    </div>

    <ul v-if="isOpen(id)" class="children">
      <TreeNode
        v-for="child in props.node.children"
        :key="child.folder!.id"
        :node="child"
        :depth="props.depth + 1"
      />
      <FolderDraft v-if="isDrafting(id)" :depth="props.depth + 1" />
      <RecordingRow
        v-for="recording in props.node.recordings"
        :key="recording.id"
        :recording="recording"
        :depth="props.depth + 1"
      />
      <li
        v-if="empty"
        class="empty muted"
        :style="{ paddingLeft: indent(props.depth + 1) }"
      >
        Empty
      </li>
    </ul>
  </li>
</template>

<style scoped>
.children {
  margin: 0;
  padding: 0;
  list-style: none;
}

.empty {
  padding: 0.25rem 0;
  font-size: 0.82rem;
  font-style: italic;
}
</style>
