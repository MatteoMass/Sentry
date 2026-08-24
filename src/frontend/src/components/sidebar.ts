/** What the sidebar components share to draw a row. */

/** Rows are flat in the DOM, so the nesting has to be drawn by hand. */
export function indent(depth: number): string {
  return `${0.5 + depth * 0.85}rem`;
}

/** How long a folder is hovered over, dragging, before it opens itself. */
export const HOVER_OPEN_MS = 700;

/** Name a count with its unit: "1 folder", "3 recordings". */
function count(amount: number, unit: string): string {
  return `${amount} ${unit}${amount === 1 ? "" : "s"}`;
}

/**
 * What a folder holds, as a phrase a question can be built around.
 *
 * Whichever of the two is not there is left out, so nothing ever reads
 * "0 folders".
 */
export function describe(folders: number, recordings: number): string {
  const parts: string[] = [];
  if (folders) {
    parts.push(count(folders, "folder"));
  }
  if (recordings) {
    parts.push(count(recordings, "recording"));
  }
  return parts.join(" and ");
}
