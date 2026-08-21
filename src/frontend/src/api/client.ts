/**
 * The only place that talks HTTP.
 *
 * URLs are relative: in production the app is served by the same FastAPI
 * process that answers them, and in development Vite proxies them to the
 * backend, so nothing here has to know a host.
 */

import type { Folder, Recording } from "@/api/types";

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

async function request<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" } });
  } catch (cause) {
    throw new ApiError(0, `The backend is unreachable (${String(cause)}).`);
  }

  if (!response.ok) {
    throw new ApiError(response.status, await detail(response));
  }
  return (await response.json()) as T;
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

/** List the whole folder tree in one call, as the sidebar wants it. */
export function fetchFolders(): Promise<Folder[]> {
  return request<Folder[]>("/folders");
}

/** List every recording, wherever it sits, newest first. */
export function fetchRecordings(): Promise<Recording[]> {
  return request<Recording[]>("/recordings");
}
