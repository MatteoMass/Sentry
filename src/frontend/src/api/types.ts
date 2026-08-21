/** Payloads exchanged with the Sentry backend, mirroring `api/schemas.py`. */

/** How the top level is named over HTTP, where `null` cannot be spelled. */
export const ROOT = "root";

export type RecordingStatus = "to_process" | "processing" | "processed" | "error";

export const RECORDING_STATUSES: readonly RecordingStatus[] = [
  "to_process",
  "processing",
  "processed",
  "error",
];

/** A recording as the API exposes it. */
export interface Recording {
  id: string;
  name: string;
  /** ISO 8601, UTC. */
  uploaded_at: string;
  status: RecordingStatus;
  /** Folder holding it, or `null` when it sits at the top level. */
  folder: string | null;
}

/** A folder as the API exposes it. */
export interface Folder {
  id: string;
  name: string;
  parent: string | null;
  created_at: string;
  /** Recordings filed directly in it, subfolders excluded. */
  recordings: number;
}
