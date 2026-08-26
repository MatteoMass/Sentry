/**
 * Whether the left shoulder is open, and whether the window still has room
 * for it beside the recording.
 *
 * The hawk in its header collapses it, and is the only thing left of it once
 * collapsed: clicking the hawk again brings the shoulder back. A window too
 * narrow to hold both panes collapses it on its own, and widening the window
 * again reopens it — but a click is the user's word on it either way, and
 * stands until the window next crosses the breakpoint.
 *
 * Reopened on a narrow window the shoulder has nowhere to sit, so it is drawn
 * over the recording instead of beside it, on a scrim that closes it again.
 */

import { computed, readonly, ref } from "vue";

/** Under this the two panes no longer fit side by side. */
const BREAKPOINT = 900;

const narrowed = window.matchMedia(`(max-width: ${BREAKPOINT}px)`);

const narrow = ref(narrowed.matches);
const collapsed = ref(narrowed.matches);

/* Crossing the breakpoint decides again, overruling whatever was clicked
   while the window was the other size. */
narrowed.addEventListener("change", (event) => {
  narrow.value = event.matches;
  collapsed.value = event.matches;
});

/** Open over the recording rather than beside it, the window being narrow. */
const floating = computed(() => narrow.value && !collapsed.value);

function toggle(): void {
  collapsed.value = !collapsed.value;
}

export function useSidebar() {
  return {
    collapsed: readonly(collapsed),
    floating,
    toggle,
  };
}
