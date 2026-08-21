/**
 * The state the whole app reads from: the folder tree, the recordings, and
 * which one is being looked at.
 *
 * Both collections travel in one request each and are nested here rather than
 * on the server — folders are few and human made, so one round trip is
 * cheaper than one request per level, and the sidebar can redraw itself
 * without asking anything again.
 *
 * The same reasoning holds for what the user changes: creating a folder or
 * moving something answers with the row as it now stands, so that row is
 * swapped in place and nothing is fetched again.
 */

import { computed, reactive, readonly, ref } from "vue";

import {
  ApiError,
  createFolder as postFolder,
  deleteFolder,
  deleteRecording,
  fetchFolders,
  fetchRecordings,
  moveFolder,
  moveRecording,
  uploadRecording,
} from "@/api/client";
import { ROOT } from "@/api/types";
import type { Folder, Recording } from "@/api/types";

/** One level of the sidebar: a folder, what it holds, and what sits below. */
export interface TreeNode {
  /** The folder itself, or `null` for the top level. */
  folder: Folder | null;
  children: TreeNode[];
  recordings: Recording[];
}

/** Something the sidebar can pick up and file somewhere else. */
export interface DragItem {
  kind: "folder" | "recording";
  id: string;
}

/**
 * A destination as the sidebar keys it.
 *
 * A folder id, or `ROOT` for the top level: the state has to tell "the top
 * level" apart from "nowhere", which a bare `null` could not do.
 */
type Destination = string | typeof ROOT;

const folders = ref<Folder[]>([]);
const recordings = ref<Recording[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
const selectedId = ref<string | null>(null);
const collapsed = reactive(new Set<string>());

/** What went wrong on the last change, shown without hiding the tree. */
const actionError = ref<string | null>(null);

/** The files still on their way up, by the order they were chosen. */
const uploads = ref<string[]>([]);

/** Where a new folder is being named, and whether it is on its way. */
const draft = ref<Destination | null>(null);
const drafting = ref(false);

/** What is being dragged, and the folder it is currently held over. */
const dragged = ref<DragItem | null>(null);
const dropTarget = ref<Destination | null>(null);

/** Folders that hold no recording anywhere below them still show up. */
const tree = computed<TreeNode>(() => buildTree(folders.value, recordings.value));

const byId = computed(() => new Map(folders.value.map((folder) => [folder.id, folder])));

const selected = computed<Recording | null>(
  () => recordings.value.find((recording) => recording.id === selectedId.value) ?? null,
);

/** The folders leading to the selected recording, top level first. */
const selectedPath = computed<Folder[]>(() => {
  const path: Folder[] = [];
  let current = selected.value?.folder ?? null;
  while (current !== null) {
    const folder = byId.value.get(current);
    if (folder === undefined) {
      break;
    }
    path.unshift(folder);
    current = folder.parent;
  }
  return path;
});

/** Reload both collections, keeping the selection when it still exists. */
async function refresh(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const [nextFolders, nextRecordings] = await Promise.all([
      fetchFolders(),
      fetchRecordings(),
    ]);
    folders.value = nextFolders;
    recordings.value = nextRecordings;
    if (!nextRecordings.some((recording) => recording.id === selectedId.value)) {
      selectedId.value = null;
    }
  } catch (cause) {
    error.value = message(cause);
    folders.value = [];
    recordings.value = [];
    selectedId.value = null;
  } finally {
    loading.value = false;
  }
}

function select(recordingId: string): void {
  selectedId.value = recordingId;
}

function toggle(folderId: string): void {
  if (!collapsed.delete(folderId)) {
    collapsed.add(folderId);
  }
}

function isOpen(folderId: string): boolean {
  return !collapsed.has(folderId);
}

function expand(folderId: string): void {
  collapsed.delete(folderId);
}

function dismissError(): void {
  actionError.value = null;
}

// ------------------------------------------------------------ new folders

/**
 * Start naming a new folder inside `parent`, `null` for the top level.
 *
 * Nothing is created yet: the sidebar draws an empty row the user types into,
 * the way a file manager does, and the folder exists once that row is
 * committed.
 */
function beginDraft(parent: string | null): void {
  actionError.value = null;
  draft.value = parent ?? ROOT;
  if (parent !== null) {
    // The row is drawn among the children, which have to be visible.
    expand(parent);
  }
}

function cancelDraft(): void {
  draft.value = null;
}

/** True when the row being named belongs to this folder. */
function isDrafting(parent: string | null): boolean {
  return draft.value === (parent ?? ROOT);
}

/**
 * Create the folder being named, unless the name is empty.
 *
 * A refused name — one a sibling already carries — leaves the row open with
 * what was typed still in it, so it can be fixed rather than typed again.
 */
async function commitDraft(name: string): Promise<void> {
  const parent = draft.value;
  if (parent === null || drafting.value) {
    return;
  }

  const cleaned = name.trim();
  if (cleaned === "") {
    cancelDraft();
    return;
  }

  drafting.value = true;
  try {
    const folder = await postFolder(cleaned, parent === ROOT ? null : parent);
    folders.value = [...folders.value, folder];
    draft.value = null;
    actionError.value = null;
  } catch (cause) {
    actionError.value = message(cause);
  } finally {
    drafting.value = false;
  }
}

// --------------------------------------------------------------- uploading

/**
 * Store media files under `folder`, `null` for the top level.
 *
 * They go up one at a time: a batch is usually two or three files, and one
 * request at a time keeps the order of what appears in the sidebar readable.
 * A file the backend turns down — anything that is not audio or video — is
 * reported without holding back the ones that follow.
 */
async function upload(files: readonly File[], folder: string | null): Promise<void> {
  if (files.length === 0) {
    return;
  }
  actionError.value = null;

  const failures: string[] = [];
  for (const file of files) {
    uploads.value.push(file.name);
    try {
      const recording = await uploadRecording(file, folder);
      recordings.value = [...recordings.value, recording];
      // The upload is worth showing: it is what the user just asked for.
      selectedId.value = recording.id;
    } catch (cause) {
      failures.push(`${file.name}: ${message(cause)}`);
    } finally {
      uploads.value.splice(uploads.value.indexOf(file.name), 1);
    }
  }

  if (folder !== null) {
    expand(folder);
  }
  if (failures.length) {
    actionError.value = failures.join(" · ");
  }
}

// ------------------------------------------------------------------ moving

function startDrag(item: DragItem): void {
  dragged.value = item;
  dropTarget.value = null;
}

function endDrag(): void {
  dragged.value = null;
  dropTarget.value = null;
}

/** Remember the folder the pointer is over, `null` for the top level. */
function markTarget(folderId: string | null): void {
  dropTarget.value = folderId ?? ROOT;
}

/** Forget a folder, unless the pointer has already moved on to another. */
function clearTarget(folderId: string | null): void {
  if (dropTarget.value === (folderId ?? ROOT)) {
    dropTarget.value = null;
  }
}

function isTarget(folderId: string | null): boolean {
  return dropTarget.value === (folderId ?? ROOT);
}

/**
 * True when what is being dragged may be filed into `folderId`.
 *
 * A move that would change nothing is refused as well, so the row it started
 * from never lights up as a destination.
 */
function canDropInto(folderId: string | null): boolean {
  const item = dragged.value;
  if (item === null) {
    return false;
  }

  if (item.kind === "recording") {
    const recording = recordings.value.find((candidate) => candidate.id === item.id);
    return recording !== undefined && recording.folder !== folderId;
  }

  const folder = byId.value.get(item.id);
  if (folder === undefined || folder.parent === folderId) {
    return false;
  }
  // A folder cannot be filed into itself, nor into anything below it: the
  // backend refuses it too, but the row should not invite the drop.
  return folderId === null || !isBelow(folderId, folder.id);
}

/** True when `folderId` is `ancestorId`, or sits anywhere below it. */
function isBelow(folderId: string, ancestorId: string): boolean {
  let current: string | null = folderId;
  while (current !== null) {
    if (current === ancestorId) {
      return true;
    }
    current = byId.value.get(current)?.parent ?? null;
  }
  return false;
}

/** File what is being dragged into `folderId`, `null` for the top level. */
async function dropInto(folderId: string | null): Promise<void> {
  const item = dragged.value;
  const allowed = canDropInto(folderId);
  endDrag();
  if (item === null || !allowed) {
    return;
  }

  try {
    if (item.kind === "recording") {
      const moved = await moveRecording(item.id, folderId);
      recordings.value = recordings.value.map((recording) =>
        recording.id === moved.id ? moved : recording,
      );
    } else {
      const moved = await moveFolder(item.id, folderId);
      folders.value = folders.value.map((folder) =>
        folder.id === moved.id ? moved : folder,
      );
    }
    if (folderId !== null) {
      // Whatever landed there should be in sight.
      expand(folderId);
    }
    actionError.value = null;
  } catch (cause) {
    actionError.value = message(cause);
  }
}

// ---------------------------------------------------------------- deleting

/**
 * Delete a recording, media included.
 *
 * What the pipeline knows about it goes with it: the backend drops the row
 * and the folder holding the files, so nothing is left to clean up by hand.
 */
async function removeRecording(recordingId: string): Promise<void> {
  try {
    await deleteRecording(recordingId);
    recordings.value = recordings.value.filter(
      (recording) => recording.id !== recordingId,
    );
    if (selectedId.value === recordingId) {
      selectedId.value = null;
    }
    actionError.value = null;
  } catch (cause) {
    actionError.value = message(cause);
  }
}

/**
 * Delete a folder, with `recursive` taking everything below it as well.
 *
 * The branch is dropped from the local state rather than fetched again: the
 * backend has just said the whole of it is gone, and it is the caller that
 * asked for exactly that.
 */
async function removeFolder(folderId: string, recursive: boolean): Promise<void> {
  try {
    await deleteFolder(folderId, recursive);
    const gone = subtree(folderId);
    folders.value = folders.value.filter((folder) => !gone.has(folder.id));
    recordings.value = recordings.value.filter(
      (recording) => recording.folder === null || !gone.has(recording.folder),
    );
    if (!recordings.value.some((recording) => recording.id === selectedId.value)) {
      selectedId.value = null;
    }
    actionError.value = null;
  } catch (cause) {
    actionError.value = message(cause);
  }
}

/** How much a folder holds, at any depth, as a delete has to say. */
function contents(folderId: string): { folders: number; recordings: number } {
  const gone = subtree(folderId);
  return {
    // The folder itself is in the subtree, and is not part of what it holds.
    folders: gone.size - 1,
    recordings: recordings.value.filter(
      (recording) => recording.folder !== null && gone.has(recording.folder),
    ).length,
  };
}

/** The folder and every folder below it. */
function subtree(folderId: string): Set<string> {
  return new Set(
    folders.value
      .filter((folder) => isBelow(folder.id, folderId))
      .map((folder) => folder.id),
  );
}

// ----------------------------------------------------------------- helpers

/** Nest the flat listings the API returns into the tree the sidebar draws. */
function buildTree(allFolders: Folder[], allRecordings: Recording[]): TreeNode {
  const root: TreeNode = { folder: null, children: [], recordings: [] };
  const nodes = new Map<string, TreeNode>();

  for (const folder of allFolders) {
    nodes.set(folder.id, { folder, children: [], recordings: [] });
  }
  for (const folder of allFolders) {
    // A folder whose parent is missing from the listing would disappear
    // silently, so it is shown at the top level instead.
    const parent = folder.parent === null ? root : (nodes.get(folder.parent) ?? root);
    parent.children.push(nodes.get(folder.id)!);
  }
  for (const recording of allRecordings) {
    const holder =
      recording.folder === null ? root : (nodes.get(recording.folder) ?? root);
    holder.recordings.push(recording);
  }

  sort(root);
  return root;
}

/** Order every level: folders by name, recordings newest first. */
function sort(node: TreeNode): void {
  node.children.sort((left, right) =>
    left.folder!.name.localeCompare(right.folder!.name),
  );
  node.recordings.sort((left, right) =>
    right.uploaded_at.localeCompare(left.uploaded_at),
  );
  node.children.forEach(sort);
}

/** What to show the user about a failure. */
function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : String(cause);
}

export function useLibrary() {
  return {
    folders: readonly(folders),
    recordings: readonly(recordings),
    loading: readonly(loading),
    error: readonly(error),
    actionError: readonly(actionError),
    selectedId: readonly(selectedId),
    dragged: readonly(dragged),
    drafting: readonly(drafting),
    uploads: readonly(uploads),
    selected,
    selectedPath,
    tree,
    refresh,
    select,
    toggle,
    isOpen,
    expand,
    dismissError,
    beginDraft,
    cancelDraft,
    commitDraft,
    isDrafting,
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
    removeRecording,
  };
}
