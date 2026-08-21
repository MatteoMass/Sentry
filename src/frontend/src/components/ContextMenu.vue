<script setup lang="ts">
/**
 * The floating menu, drawn at the pointer.
 *
 * It is teleported to the body so the sidebar, which clips what overflows it,
 * cannot cut it off, and it is clamped to the window so an entry opened near
 * an edge stays reachable.
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { useContextMenu } from "@/composables/useContextMenu";

const { anchor, entries, close, choose } = useContextMenu();

const menu = ref<HTMLElement | null>(null);
const position = ref({ x: 0, y: 0 });

/** Space kept between the menu and the edge it would otherwise cross. */
const MARGIN = 8;

watch(anchor, async (at) => {
  if (at === null) {
    return;
  }
  position.value = at;
  // The size is only known once the menu is in the document, so it is placed
  // at the pointer first and pulled back inside the window right after.
  await nextTick();
  const element = menu.value;
  if (element === null) {
    return;
  }
  const { width, height } = element.getBoundingClientRect();
  position.value = {
    x: Math.max(MARGIN, Math.min(at.x, window.innerWidth - width - MARGIN)),
    y: Math.max(MARGIN, Math.min(at.y, window.innerHeight - height - MARGIN)),
  };
});

/** Anything happening outside the menu dismisses it. */
function onPointerDown(event: PointerEvent): void {
  if (!menu.value?.contains(event.target as Node)) {
    close();
  }
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    close();
  }
}

onMounted(() => {
  window.addEventListener("pointerdown", onPointerDown, true);
  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("resize", close);
  // Capturing catches the sidebar scrolling, which does not reach the window.
  window.addEventListener("scroll", close, true);
});

onBeforeUnmount(() => {
  window.removeEventListener("pointerdown", onPointerDown, true);
  window.removeEventListener("keydown", onKeyDown);
  window.removeEventListener("resize", close);
  window.removeEventListener("scroll", close, true);
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="anchor !== null"
      ref="menu"
      class="menu"
      role="menu"
      :style="{ left: `${position.x}px`, top: `${position.y}px` }"
      @contextmenu.prevent
    >
      <button
        v-for="entry in entries"
        :key="entry.label"
        class="entry"
        :class="{ 'entry--danger': entry.danger }"
        role="menuitem"
        type="button"
        @click="choose(entry)"
      >
        {{ entry.label }}
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.menu {
  position: fixed;
  z-index: 10;
  display: flex;
  flex-direction: column;
  min-width: 170px;
  padding: 0.25rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: 0 10px 30px rgb(0 0 0 / 18%);
}

.entry {
  padding: 0.35rem 0.6rem;
  border: 0;
  border-radius: calc(var(--radius) - 2px);
  background: none;
  font-size: 0.88rem;
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
}

.entry:hover {
  background: var(--surface-hover);
}

.entry--danger {
  color: var(--status-error);
}
</style>
