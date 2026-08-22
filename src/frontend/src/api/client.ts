/**
 * The only place that talks HTTP.
 *
 * URLs are relative: in production the app is served by the same FastAPI
 * process that answers them, and in development Vite proxies them to the
 * backend, so nothing here has to know a host.
 */

import { ROOT } from "@/api/types";
import type { Folder, Recording, Summary, Transcript } from "@/api/types";

/** Raised when the backend answers with a status outside 2xx. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** What a request carries beyond its path; a plain GET needs neither. */
interface Options {
  method?: string;
  /** A JSON payload, or a form when a file has to travel with it. */
  body?: unknown;
}

/** Make the call, and let a status outside 2xx travel as an `ApiError`. */
async function send(path: string, options: Options = {}): Promise<Response> {
  const { method = "GET", body } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  let payload: FormData | string | undefined;
  if (body instanceof FormData) {
    // A form types itself: only the browser knows the boundary it picked.
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(path, { method, headers, body: payload });
  } catch (cause) {
    throw new ApiError(0, `The backend is unreachable (${String(cause)}).`);
  }

  if (!response.ok) {
    throw new ApiError(response.status, await detail(response));
  }
  return response;
}

/** Make the call and read the payload back. */
async function request<T>(path: string, options: Options = {}): Promise<T> {
  return (await send(path, options)).json() as T;
}

/** Return the `detail` the backend sends with an error, or a fallback. */
async function detail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    /* The body was not JSON; the status alone will have to do. */
  }
  return `${response.status} ${response.statusText}`;
}

/**
 * How a destination is spelled over HTTP.
 *
 * The API has no way to read a null out of a payload that means "leave it
 * alone", so the top level travels as a word instead.
 */
function ref(folderId: string | null): string {
  return folderId ?? ROOT;
}

/** A delete answers with nothing at all, which is what 204 means. */
async function discard(path: string): Promise<void> {
  await send(path, { method: "DELETE" });
}

/** List the whole folder tree in one call, as the sidebar wants it. */
export function fetchFolders(): Promise<Folder[]> {
  return request<Folder[]>("/folders");
}

/** List every recording, wherever it sits, newest first. */
export function fetchRecordings(): Promise<Recording[]> {
  return request<Recording[]>("/recordings");
}

/** Read one recording, which is how its status is followed while it runs. */
export function fetchRecording(recordingId: string): Promise<Recording> {
  return request<Recording>(`/recordings/${encodeURIComponent(recordingId)}`);
}

/**
 * Start the whole pipeline on a recording: transcript, diarization, summary.
 *
 * The answer comes back long before the work is done — it only says which
 * step the recording is now in. What became of it is read from its status
 * afterwards.
 *
 * With `force` the audio is transcribed again from scratch; without it a run
 * reuses whatever the last one already managed to store, which is what makes
 * retrying a failure cheap.
 */
export function processRecording(
  recordingId: string,
  force: boolean,
): Promise<Recording> {
  return request<Recording>(
    `/recordings/${encodeURIComponent(recordingId)}/process?force=${force}`,
    { method: "POST" },
  );
}

/**
 * Run the transcription alone, sending the audio again.
 *
 * This is the expensive half, and asking for it explicitly can only mean the
 * stored transcript is not wanted — so it is always forced, and a summary
 * describing the old dialogue is dropped by the backend along with it.
 */
export function transcribeRecording(recordingId: string): Promise<Recording> {
  return request<Recording>(
    `/recordings/${encodeURIComponent(recordingId)}/transcribe?force=true`,
    { method: "POST" },
  );
}

/**
 * Run the summarisation alone, over the transcript already stored.
 *
 * This is what a failed summary is retried with: the audio never travels
 * again, so it costs one model call. The backend turns it down with a 409
 * when there is no transcript to read.
 */
export function summarizeRecording(recordingId: string): Promise<Recording> {
  return request<Recording>(
    `/recordings/${encodeURIComponent(recordingId)}/summarize`,
    { method: "POST" },
  );
}

/** Read the stored transcript, whatever became of the summary. */
export function fetchTranscript(recordingId: string): Promise<Transcript> {
  return request<Transcript>(
    `/recordings/${encodeURIComponent(recordingId)}/transcript`,
  );
}

/** Read the stored summary. */
export function fetchSummary(recordingId: string): Promise<Summary> {
  return request<Summary>(`/recordings/${encodeURIComponent(recordingId)}/summary`);
}

/**
 * Store a media file under `folder`, or at the top level for `null`.
 *
 * It lands in `to_process`: the upload only files it, the pipeline is what
 * picks it up afterwards.
 */
export function uploadRecording(file: File, folder: string | null): Promise<Recording> {
  const form = new FormData();
  form.append("file", file);
  form.append("folder", ref(folder));
  return request<Recording>("/recordings", { method: "POST", body: form });
}

/** Create an empty folder under `parent`, or at the top level for `null`. */
export function createFolder(name: string, parent: string | null): Promise<Folder> {
  return request<Folder>("/folders", {
    method: "POST",
    body: { name, parent: ref(parent) },
  });
}

/** File a folder, and everything below it, under another one. */
export function moveFolder(folderId: string, parent: string | null): Promise<Folder> {
  return request<Folder>(`/folders/${encodeURIComponent(folderId)}`, {
    method: "PATCH",
    body: { parent: ref(parent) },
  });
}

/** File a recording under another folder. */
export function moveRecording(
  recordingId: string,
  folder: string | null,
): Promise<Recording> {
  return request<Recording>(
    `/recordings/${encodeURIComponent(recordingId)}/folder`,
    { method: "PATCH", body: { folder: ref(folder) } },
  );
}

/** Delete a recording, media included. */
export function deleteRecording(recordingId: string): Promise<void> {
  return discard(`/recordings/${encodeURIComponent(recordingId)}`);
}

/**
 * Delete a folder.
 *
 * Emptying a branch is an explicit choice: without `recursive` the backend
 * refuses to take anything down with the folder.
 */
export function deleteFolder(folderId: string, recursive: boolean): Promise<void> {
  return discard(
    `/folders/${encodeURIComponent(folderId)}?recursive=${recursive}`,
  );
}
