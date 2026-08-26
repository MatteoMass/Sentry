<script setup lang="ts">
/**
 * The left shoulder: the folder tree, and under each folder the recordings
 * filed there, by name.
 *
 * This is also the top level itself — a right click on its empty space, like
 * the button in the header, adds a folder or a recording there, and a drop
 * released outside every folder files what was dragged back out.
 *
 * The whole shoulder folds away to the hawk in its header; what is left of it
 * then is that hawk, which unfolds it again.
 */
import { computed } from "vue";

import ConfirmDialog from "@/components/ConfirmDialog.vue";
import ContextMenu from "@/components/ContextMenu.vue";
import FolderDraft from "@/components/FolderDraft.vue";
import RecordingRow from "@/components/RecordingRow.vue";
import SettingsDialog from "@/components/SettingsDialog.vue";
import TreeNode from "@/components/TreeNode.vue";
import { useContextMenu } from "@/composables/useContextMenu";
import { pickMedia } from "@/composables/useFilePicker";
import { useLibrary } from "@/composables/useLibrary";
import { useSettings } from "@/composables/useSettings";
import { useSidebar } from "@/composables/useSidebar";

const {
  tree,
  loading,
  error,
  actionError,
  recordings,
  dragged,
  uploads,
  refresh,
  dismissError,
  beginDraft,
  isDrafting,
  upload,
  markTarget,
  clearTarget,
  isTarget,
  canDropInto,
  dropInto,
} = useLibrary();
const { open, openAt } = useContextMenu();
const { openSettings } = useSettings();
const { collapsed, floating, toggle } = useSidebar();

const empty = computed(
  () => !tree.value.children.length && !tree.value.recordings.length,
);

/** True while a drop released here would file the item at the top level. */
const highlighted = computed(() => isTarget(null));

/** What can be added at the top level, offered from the header and the tree. */
function entries() {
  return [
    { label: "New folder", run: () => beginDraft(null) },
    { label: "Upload recording…", run: () => void uploadHere() },
  ];
}

/** Ask for files and store them at the top level. */
async function uploadHere(): Promise<void> {
  await upload(await pickMedia(), null);
}

function onContextMenu(event: MouseEvent): void {
  open(event, entries());
}

/** The header button offers the same, hanging under itself. */
function onAdd(event: MouseEvent): void {
  const button = (event.currentTarget as HTMLElement).getBoundingClientRect();
  openAt({ x: button.left, y: button.bottom + 4 }, entries());
}

/** What the sidebar says while files are on their way up. */
const progress = computed(() =>
  uploads.value.length === 1
    ? `Uploading ${uploads.value[0]}…`
    : `Uploading ${uploads.value.length} recordings…`,
);

/** The top level catches every release no folder claimed first. */
function onDragOver(event: DragEvent): void {
  if (dragged.value === null || !canDropInto(null)) {
    return;
  }
  event.preventDefault();
  if (event.dataTransfer !== null) {
    event.dataTransfer.dropEffect = "move";
  }
  markTarget(null);
}

function onDrop(event: DragEvent): void {
  if (dragged.value === null) {
    return;
  }
  event.preventDefault();
  void dropInto(null);
}
</script>

<template>
  <aside
    class="sidebar"
    :class="{
      'sidebar--collapsed': collapsed,
      'sidebar--floating': floating,
    }"
  >
    <header class="header">
      <div class="brand">
        <!-- The hawk doubles as the handle: it folds the shoulder away, and
             is the one thing left of it to unfold it again. -->
        <button
          class="hawk"
          type="button"
          :title="collapsed ? 'Show the sidebar' : 'Hide the sidebar'"
          :aria-expanded="!collapsed"
          @click="toggle"
        >
          <img class="logo" src="/favicon.png" alt="Sentry" />
        </button>
        <h1 v-if="!collapsed" class="title">Sentry</h1>
      </div>
      <div v-if="!collapsed" class="actions">
        <button class="action" title="Add" @click="onAdd">＋</button>
        <button class="action" :disabled="loading" title="Reload" @click="refresh">
          {{ loading ? "…" : "↻" }}
        </button>
        <button class="action" title="Settings" @click="openSettings">⚙</button>
      </div>
    </header>

    <!-- Everything below the header is what folding away puts away. -->
    <template v-if="!collapsed">
      <p v-if="uploads.length" class="state muted">{{ progress }}</p>

      <p v-if="actionError" class="notice">
        <span class="notice-text">{{ actionError }}</span>
        <button class="dismiss" title="Dismiss" @click="dismissError">×</button>
      </p>

      <p v-if="error" class="error">{{ error }}</p>

      <p v-else-if="loading && !recordings.length" class="state muted">
        Loading…
      </p>

      <nav
        v-else
        class="tree"
        :class="{ 'tree--drop': highlighted }"
        aria-label="Recordings"
        @contextmenu="onContextMenu"
        @dragover="onDragOver"
        @dragleave="clearTarget(null)"
        @drop="onDrop"
      >
        <ul class="level">
          <TreeNode
            v-for="child in tree.children"
            :key="child.folder!.id"
            :node="child"
            :depth="0"
          />
          <FolderDraft v-if="isDrafting(null)" :depth="0" />
          <RecordingRow
            v-for="recording in tree.recordings"
            :key="recording.id"
            :recording="recording"
            :depth="0"
          />
        </ul>

        <p v-if="empty && !isDrafting(null)" class="state muted">
          Nothing stored yet. Right click to add a folder or a recording.
        </p>
      </nav>
    </template>

    <ContextMenu />
    <ConfirmDialog />
    <SettingsDialog />
  </aside>

  <!-- What the shoulder stands on when it has to cover the recording: a tap
       anywhere off it folds it back to the hawk. -->
  <Teleport to="body">
    <div v-if="floating" class="scrim" @click="toggle"></div>
  </Teleport>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width);
  min-width: 220px;
  height: 100%;
  border-right: 1px solid var(--border);
  background: var(--surface);
  overflow: hidden;
  transition:
    width 160ms ease,
    min-width 160ms ease;
}

/* Folded away: a rail exactly as wide as the hawk it is down to. */
.sidebar--collapsed {
  flex: none;
  width: var(--sidebar-rail);
  min-width: 0;
}

/* Unfolded on a window with no room for it, so it stands over the recording
   instead of beside it, and casts its own edge. */
.sidebar--floating {
  position: absolute;
  z-index: 5;
  top: 0;
  bottom: 0;
  left: 0;
  box-shadow: 0 0 2rem rgb(0 0 0 / 25%);
}

.scrim {
  position: fixed;
  z-index: 4;
  inset: 0;
  background: rgb(0 0 0 / 30%);
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.9rem 1rem;
  border-bottom: 1px solid var(--border);
}

/* The rail is only the hawk, so it is centred in it rather than to a side. */
.sidebar--collapsed .header {
  justify-content: center;
  padding: 0.9rem 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.hawk {
  display: flex;
  flex: none;
  padding: 0.15rem;
  border: 0;
  border-radius: 0.4rem;
  background: none;
  cursor: pointer;
}

.hawk:hover {
  background: var(--surface-hover);
}

.logo {
  width: 1.35rem;
  height: 1.35rem;
  border-radius: 0.3rem;
  flex-shrink: 0;
}

.title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.actions {
  display: flex;
  gap: 0.3rem;
}

.action {
  padding: 0.15rem 0.45rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: none;
  cursor: pointer;
}

.action:hover:not(:disabled) {
  background: var(--surface-hover);
}

.action:disabled {
  cursor: default;
  opacity: 0.6;
}

.tree {
  flex: 1;
  padding: 0.5rem;
  overflow: auto;
}

/* The top level lights up as a whole, having no row of its own. */
.tree--drop {
  border-radius: var(--radius);
  box-shadow: inset 0 0 0 1.5px var(--accent);
}

.level {
  margin: 0;
  padding: 0;
  list-style: none;
}

.state,
.error {
  margin: 0;
  padding: 1rem;
  font-size: 0.88rem;
}

.error {
  color: var(--status-error);
}

.notice {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  margin: 0.5rem 0.5rem 0;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--status-error);
  border-radius: var(--radius);
  color: var(--status-error);
  font-size: 0.82rem;
}

.notice-text {
  flex: 1;
}

.dismiss {
  flex: none;
  padding: 0 0.2rem;
  border: 0;
  background: none;
  line-height: 1;
  cursor: pointer;
}
</style>
