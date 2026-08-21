<script setup lang="ts">
/**
 * One folder of the sidebar and everything it holds.
 *
 * The component renders itself for the levels below, so the tree can be as
 * deep as the user made it.
 */
import type { TreeNode as Node } from "@/composables/useLibrary";
import { useLibrary } from "@/composables/useLibrary";

const props = defineProps<{ node: Node; depth: number }>();

const { selectedId, select, toggle, isOpen } = useLibrary();

/** Rows are flat in the DOM, so the nesting has to be drawn by hand. */
function indent(depth: number): string {
  return `${0.5 + depth * 0.85}rem`;
}
</script>

<template>
  <li class="node">
    <button
      class="row row--folder"
      :style="{ paddingLeft: indent(props.depth) }"
      :aria-expanded="isOpen(props.node.folder!.id)"
      @click="toggle(props.node.folder!.id)"
    >
      <span class="chevron" :class="{ 'chevron--open': isOpen(props.node.folder!.id) }">
        ›
      </span>
      <span class="label">{{ props.node.folder!.name }}</span>
      <span v-if="props.node.recordings.length" class="count">
        {{ props.node.recordings.length }}
      </span>
    </button>

    <ul v-if="isOpen(props.node.folder!.id)" class="children">
      <TreeNode
        v-for="child in props.node.children"
        :key="child.folder!.id"
        :node="child"
        :depth="props.depth + 1"
      />
      <li v-for="recording in props.node.recordings" :key="recording.id">
        <button
          class="row row--recording"
          :class="{ 'row--selected': recording.id === selectedId }"
          :style="{ paddingLeft: indent(props.depth + 1) }"
          :title="recording.name"
          @click="select(recording.id)"
        >
          <span class="label">{{ recording.name }}</span>
        </button>
      </li>
      <li
        v-if="!props.node.children.length && !props.node.recordings.length"
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

.row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  padding: 0.3rem 0.6rem 0.3rem 0;
  border: 0;
  border-radius: var(--radius);
  background: none;
  text-align: left;
  cursor: pointer;
}

.row:hover {
  background: var(--surface-hover);
}

.row--folder {
  font-weight: 500;
}

.row--recording {
  color: var(--text-muted);
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

.chevron {
  flex: none;
  width: 0.8rem;
  color: var(--text-muted);
  transition: transform 120ms ease;
}

.chevron--open {
  transform: rotate(90deg);
}

.count {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 0.78rem;
  font-weight: 400;
}

.empty {
  padding: 0.25rem 0;
  font-size: 0.82rem;
  font-style: italic;
}
</style>
