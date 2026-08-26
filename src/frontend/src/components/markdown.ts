/**
 * Just enough Markdown to read an answer by.
 *
 * A model asked for prose answers in Markdown whether or not anybody asked
 * for Markdown: a list of names comes back as bullets, a quotation from the
 * transcript comes back fenced, and emphasis comes back in asterisks. Shown
 * raw, all of it is punctuation in the way of the answer.
 *
 * So the text is parsed here into blocks and pieces, and drawn as real
 * elements by `Markdown.vue`. Nothing is ever turned into HTML on the way —
 * which is the point: the text was written by a model reading a recording
 * somebody else uploaded, and it is never in a position to bring markup of
 * its own into the page.
 *
 * What is supported is what an answer actually uses: headings, paragraphs,
 * bullet and numbered lists, quotations, fenced code, rules, and inline
 * bold, italic, code and links. Anything else survives as the text it was
 * written as, which is the right failure for a parser this small.
 */

/** One run of inline text, and what it is drawn as. */
export type Piece =
  | { kind: "text"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "emphasis"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string };

/** One block of the answer, in the order it is read. */
export type Block =
  | { kind: "text"; tag: "p" | "h1" | "h2" | "h3" | "h4" | "blockquote"; pieces: Piece[] }
  | { kind: "list"; ordered: boolean; items: Piece[][] }
  | { kind: "code"; text: string }
  | { kind: "rule" };

const FENCE = /^\s*```/;
const RULE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;
const BULLET = /^\s{0,3}[-*+]\s+(.*)$/;
const NUMBERED = /^\s{0,3}\d+[.)]\s+(.*)$/;

/**
 * The inline grammar, in the order the alternatives must be tried.
 *
 * Code comes first because nothing inside a span of code is markup, and the
 * doubled markers come before the single ones so that `**bold**` is not read
 * as an emphasis wrapping an asterisk. A marker with blank space just inside
 * it is not a marker at all, which is what keeps `5 * 3` and an asterisk
 * nobody closed from italicising the rest of a sentence.
 *
 * A lone underscore is not a marker here. Emphasis written that way is rare
 * in an answer and `snake_case` is not, so reading one as the other would
 * cost more than it is worth.
 */
const INLINE =
  /(`+)(.+?)\1|\*\*(\S(?:[\s\S]*?\S)?)\*\*|__(\S(?:[\s\S]*?\S)?)__|\*([^\s*](?:[^*]*[^\s*])?)\*|\[([^\]\n]+)\]\(([^)\s]+)\)/g;

/** Schemes a link may carry; anything else is drawn as the text it is. */
const SCHEMES = ["http:", "https:", "mailto:"];

/**
 * Read a Markdown answer as the blocks it is made of.
 *
 * The scan is line by line and never backtracks: a line either opens a block
 * of its own or continues the one before it, which is what keeps a wrapped
 * bullet one bullet instead of two.
 */
export function blocks(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const found: Block[] = [];
  let at = 0;

  while (at < lines.length) {
    const line = lines[at];

    if (line.trim() === "") {
      at += 1;
      continue;
    }

    if (FENCE.test(line)) {
      const opened = at;
      at += 1;
      while (at < lines.length && !FENCE.test(lines[at])) {
        at += 1;
      }
      found.push({ kind: "code", text: lines.slice(opened + 1, at).join("\n") });
      // The closing fence is a line of its own, unless the text simply ended.
      at += 1;
      continue;
    }

    if (RULE.test(line)) {
      found.push({ kind: "rule" });
      at += 1;
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      // Nothing above a level four: an answer sits inside a panel that
      // already has headings of its own, and must not shout over them.
      const level = Math.min(heading[1].length, 4);
      found.push({
        kind: "text",
        tag: `h${level}` as "h1" | "h2" | "h3" | "h4",
        pieces: inline(heading[2]),
      });
      at += 1;
      continue;
    }

    if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = NUMBERED.test(line);
      const items: Piece[][] = [];
      while (at < lines.length) {
        const entry = (ordered ? NUMBERED : BULLET).exec(lines[at]);
        if (entry) {
          items.push(inline(entry[1]));
          at += 1;
          continue;
        }
        // A line that opens nothing continues the item above it.
        if (items.length && lines[at].trim() !== "" && !opensBlock(lines[at])) {
          items[items.length - 1] = inline(
            text(items[items.length - 1]) + " " + lines[at].trim(),
          );
          at += 1;
          continue;
        }
        break;
      }
      found.push({ kind: "list", ordered, items });
      continue;
    }

    const quote = QUOTE.exec(line);
    if (quote) {
      const said: string[] = [quote[1]];
      at += 1;
      while (at < lines.length) {
        const more = QUOTE.exec(lines[at]);
        if (more === null) {
          break;
        }
        said.push(more[1]);
        at += 1;
      }
      found.push({ kind: "text", tag: "blockquote", pieces: inline(said.join(" ")) });
      continue;
    }

    const paragraph: string[] = [];
    while (at < lines.length && lines[at].trim() !== "" && !opensBlock(lines[at])) {
      paragraph.push(lines[at].trim());
      at += 1;
    }
    // A line that opens nothing and started nothing is a paragraph of one.
    if (paragraph.length === 0) {
      paragraph.push(lines[at].trim());
      at += 1;
    }
    found.push({ kind: "text", tag: "p", pieces: inline(paragraph.join(" ")) });
  }

  return found;
}

/** Read one line of text as the runs it is made of. */
export function inline(source: string): Piece[] {
  const pieces: Piece[] = [];
  let from = 0;

  INLINE.lastIndex = 0;
  for (let found = INLINE.exec(source); found !== null; found = INLINE.exec(source)) {
    if (found.index > from) {
      pieces.push({ kind: "text", text: source.slice(from, found.index) });
    }
    pieces.push(piece(found));
    from = found.index + found[0].length;
  }

  if (from < source.length) {
    pieces.push({ kind: "text", text: source.slice(from) });
  }
  return pieces;
}

/** Turn one match of the inline grammar into the run it stands for. */
function piece(found: RegExpExecArray): Piece {
  const [, , code, strong, alsoStrong, emphasis, label, href] = found;
  if (code !== undefined) {
    return { kind: "code", text: code };
  }
  if (strong !== undefined || alsoStrong !== undefined) {
    return { kind: "strong", text: strong ?? alsoStrong };
  }
  if (emphasis !== undefined) {
    return { kind: "emphasis", text: emphasis };
  }
  return safe(href) ? { kind: "link", text: label, href } : { kind: "text", text: label };
}

/**
 * Tell whether a link is one worth making clickable.
 *
 * The text is written by a model, so the scheme is checked rather than
 * trusted: a `javascript:` href reaching an anchor would be markup smuggled
 * in as prose.
 */
function safe(href: string): boolean {
  try {
    return SCHEMES.includes(new URL(href, window.location.href).protocol);
  } catch {
    return false;
  }
}

/** Read a run of pieces back as the text they were written as. */
function text(pieces: Piece[]): string {
  return pieces
    .map((found) => {
      switch (found.kind) {
        case "strong":
          return `**${found.text}**`;
        case "emphasis":
          return `*${found.text}*`;
        case "code":
          return `\`${found.text}\``;
        case "link":
          return `[${found.text}](${found.href})`;
        default:
          return found.text;
      }
    })
    .join("");
}

/** True when a line starts a block rather than continuing one. */
function opensBlock(line: string): boolean {
  return (
    FENCE.test(line) ||
    RULE.test(line) ||
    HEADING.test(line) ||
    QUOTE.test(line) ||
    BULLET.test(line) ||
    NUMBERED.test(line)
  );
}
