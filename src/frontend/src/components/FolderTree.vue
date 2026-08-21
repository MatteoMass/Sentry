<script setup lang="ts">
/**
 * The left shoulder: the folder tree, and under each folder the recordings
 * filed there, by name.
 */
import TreeNode from "@/components/TreeNode.vue";
import { useLibrary } from "@/composables/useLibrary";

const { tree, loading, error, recordings, selectedId, select, refresh } = useLibrary();
</script>

<template>
  <aside class="sidebar">
    <header class="header">
      <h1 class="title">Sentry</h1>
      <button class="refresh" :disabled="loading" title="Reload" @click="refresh">
        {{ loading ? "…" : "↻" }}
      </button>
    </header>

    <p v-if="error" class="error">{{ error }}</p>

    <p v-else-if="loading && !recordings.length" class="state muted">Loading…</p>

    <p
      v-else-if="!tree.children.length && !tree.recordings.length"
      class="state muted"
    >
      Nothing stored yet.
    </p>

    <nav v-else class="tree" aria-label="Recordings">
      <ul class="level">
        <TreeNode
          v-for="child in tree.children"
          :key="child.folder!.id"
          :node="child"
          :depth="0"
        />
        <li v-for="recording in tree.recordings" :key="recording.id">
          <button
            class="row"
            :class="{ 'row--selected': recording.id === selectedId }"
            :title="recording.name"
            @click="select(recording.id)"
          >
            <span class="label">{{ recording.name }}</span>
          </button>
        </li>
      </ul>
    </nav>
  </aside>
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
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.9rem 1rem;
  border-bottom: 1px solid var(--border);
}

.title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.refresh {
  padding: 0.15rem 0.45rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: none;
  cursor: pointer;
}

.refresh:hover:not(:disabled) {
  background: var(--surface-hover);
}

.refresh:disabled {
  cursor: default;
  opacity: 0.6;
}

.tree {
  flex: 1;
  padding: 0.5rem;
  overflow: auto;
}

.level {
  margin: 0;
  padding: 0;
  list-style: none;
}

.row {
  display: flex;
  width: 100%;
  padding: 0.3rem 0.6rem 0.3rem 0.5rem;
  border: 0;
  border-radius: var(--radius);
  background: none;
  color: var(--text-muted);
  text-align: left;
  cursor: pointer;
}

.row:hover {
  background: var(--surface-hover);
}

.row--selected,
.row--selected:hover {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 500;
}

.label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
</style>
