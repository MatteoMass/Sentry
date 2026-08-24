/** Payloads exchanged with the Sentry backend, mirroring `api/schemas.py`. */

/** How the top level is named over HTTP, where `null` cannot be spelled. */
export const ROOT = "root";

/**
 * Where a recording sits in a pipeline made of two steps.
 *
 * Transcribing costs minutes, summarising seconds, and they fail apart: a
 * recording that reached `transcribed` keeps its dialogue whatever becomes of
 * the summary, which is what the panel offers to generate on its own.
 */
export type RecordingStatus =
  | "to_process"
  | "transcribing"
  | "transcribed"
  | "summarizing"
  | "processed"
  | "error";

export const RECORDING_STATUSES: readonly RecordingStatus[] = [
  "to_process",
  "transcribing",
  "transcribed",
  "summarizing",
  "processed",
  "error",
];

/** The statuses that mean the backend is holding the recording right now. */
export const RUNNING_STATUSES: readonly RecordingStatus[] = [
  "transcribing",
  "summarizing",
];

/** True while a step is running on the recording, whoever started it. */
export function isRunningStatus(status: RecordingStatus): boolean {
  return RUNNING_STATUSES.includes(status);
}

/** A recording as the API exposes it. */
export interface Recording {
  id: string;
  name: string;
  /** ISO 8601, UTC. */
  uploaded_at: string;
  status: RecordingStatus;
  /** Folder holding it, or `null` when it sits at the top level. */
  folder: string | null;
  /**
   * What each step left behind.
   *
   * The status says what the pipeline last did, these say what came of it —
   * a different question, and the one that decides what can be asked for
   * next: an `error` holding a transcript needs another summary, not another
   * transcription.
   */
  has_transcript: boolean;
  has_summary: boolean;
  /**
   * Media type of the stored file, `null` when no media is stored with it.
   *
   * It is what decides whether a player is drawn at all, and whether it is
   * one with a picture: everything else about the media — where it is, how
   * long it runs — is read from the file itself once it is loaded.
   */
  media_type: string | null;
}

/** One uninterrupted run of words from a single speaker. */
export interface Utterance {
  speaker: number;
  /** Name shown for that voice, e.g. `Speaker 2`. */
  label: string;
  text: string;
  /** Offsets from the start of the audio, in seconds. */
  start: number;
  end: number;
}

/** What the transcription step produced. */
export interface Transcript {
  language: string;
  provider: string;
  model: string;
  duration: number;
  speakers: string[];
  utterances: Utterance[];
}

/** What the summarisation step produced. */
export interface Summary {
  overview: string;
  key_points: string[];
  decisions: string[];
  action_items: string[];
  model: string;
  /** The same summary, rendered as the Markdown it is stored as. */
  markdown: string;
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
