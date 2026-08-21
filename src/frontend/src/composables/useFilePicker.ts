/**
 * The file dialog of the browser, as a promise.
 *
 * The input is built on the spot rather than kept in a template: any row of
 * the sidebar can ask for files, and none of them should have to carry a
 * hidden field around to do it.
 */

/** What the backend accepts, so the dialog does not offer the rest. */
const MEDIA = "audio/*,video/*";

/**
 * Ask for media files, and answer with what was chosen.
 *
 * The result is empty when the dialog is dismissed. It has to be called from
 * a click, or the browser opens nothing at all.
 */
export function pickMedia(): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = MEDIA;
    input.multiple = true;
    input.hidden = true;

    const settle = (files: File[]): void => {
      input.remove();
      resolve(files);
    };

    input.addEventListener("change", () => settle([...(input.files ?? [])]), {
      once: true,
    });
    input.addEventListener("cancel", () => settle([]), { once: true });

    // Safari opens no dialog for an input the document does not hold.
    document.body.append(input);
    input.click();
  });
}
