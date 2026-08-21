/**
 * The state the whole app reads from: the folder tree, the recordings, and
 * which one is being looked at.
 *
 * Both collections travel in one request each and are nested here rather than
 * on the server — folders are few and human made, so one round trip is
 * cheaper than one request per level, and the sidebar can redraw itself
 * without asking anything again.
 */

import { computed, reactive, readonly, ref } from "vue";

import { ApiError, fetchFolders, fetchRecordings } from "@/api/client";
import type { Folder, Recording } from "@/api/types";

/** One level of the sidebar: a folder, what it holds, and what sits below. */
export interface TreeNode {
  /** The folder itself, or `null` for the top level. */
  folder: Folder | null;
  children: TreeNode[];
  recordings: Recording[];
}

const folders = ref<Folder[]>([]);
const recordings = ref<Recording[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
const selectedId = ref<string | null>(null);
const collapsed = reactive(new Set<string>());

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
    error.value = cause instanceof ApiError ? cause.message : String(cause);
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

export function useLibrary() {
  return {
    folders: readonly(folders),
    recordings: readonly(recordings),
    loading: readonly(loading),
    error: readonly(error),
    selectedId: readonly(selectedId),
    selected,
    selectedPath,
    tree,
    refresh,
    select,
    toggle,
    isOpen,
  };
}
