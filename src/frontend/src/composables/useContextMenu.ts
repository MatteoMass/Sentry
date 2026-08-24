/**
 * The menu a right click opens, wherever it was asked for.
 *
 * One menu is open at a time, so the state is held here rather than in the
 * component that asked for it: the sidebar draws itself recursively and any
 * of its rows can open one, without having to pass anything down.
 */

import { readonly, ref } from "vue";

/** One line of the menu. */
export interface MenuEntry {
  label: string;
  run: () => void;
  /** True when choosing it destroys something, and should read that way. */
  danger?: boolean;
}

/** Where the menu is drawn, in viewport coordinates. */
export interface MenuAnchor {
  x: number;
  y: number;
}

const anchor = ref<MenuAnchor | null>(null);
const entries = ref<MenuEntry[]>([]);

/**
 * Open the menu where the event happened.
 *
 * The browser menu is suppressed and the event is stopped, so a row can offer
 * its own entries without the area behind it adding its own.
 */
function open(event: MouseEvent, items: MenuEntry[]): void {
  event.preventDefault();
  event.stopPropagation();
  openAt({ x: event.clientX, y: event.clientY }, items);
}

/** Open the menu at a point, for what a button offers rather than a row. */
function openAt(at: MenuAnchor, items: MenuEntry[]): void {
  anchor.value = at;
  entries.value = items;
}

function close(): void {
  anchor.value = null;
  entries.value = [];
}

/** Run an entry and close, which is the only way one is ever used. */
function choose(entry: MenuEntry): void {
  close();
  entry.run();
}

export function useContextMenu() {
  return {
    anchor: readonly(anchor),
    entries: readonly(entries),
    open,
    openAt,
    close,
    choose,
  };
}
