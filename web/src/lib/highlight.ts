/** A deliberately small syntax highlighter.
 *
 * A real grammar-driven highlighter would be the single largest dependency in
 * the frontend, for file previews that are usually a dozen lines. This scanner
 * only marks what is unambiguous — strings, comments, numbers, keywords, and
 * markdown structure — and it always emits segments covering the whole input,
 * so nothing can be dropped by a bad pattern.
 */

export type Token = { text: string; cls?: string };

const KEYWORDS = new Set([
  "as", "async", "await", "break", "case", "class", "const", "continue", "def", "default",
  "elif", "else", "except", "export", "false", "finally", "for", "from", "function", "if",
  "import", "in", "is", "lambda", "let", "new", "none", "not", "null", "or", "and", "pass",
  "raise", "return", "self", "static", "struct", "switch", "then", "this", "throw", "true",
  "try", "type", "var", "while", "with", "yield",
]);

const CODE_PATTERN = new RegExp(
  [
    /"(?:[^"\\\n]|\\.)*"?/.source, // double-quoted string
    /'(?:[^'\\\n]|\\.)*'?/.source, // single-quoted string
    /`(?:[^`\\]|\\.)*`?/.source, // template string
    /(?:#|\/\/).*/.source, // line comment
    /\b\d[\d_]*(?:\.\d+)?\b/.source, // number
    /\b[A-Za-z_][A-Za-z0-9_]*\b/.source, // word (may be a keyword)
  ].join("|"),
  "g",
);

const MARKDOWN_EXT = new Set(["md", "markdown", "mdx", "txt", "rst"]);

function extension(path: string): string {
  const base = path.split(/[\\/]/).pop() ?? "";
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : "";
}

function codeLine(line: string): Token[] {
  const out: Token[] = [];
  let last = 0;
  for (const m of line.matchAll(CODE_PATTERN)) {
    const start = m.index ?? 0;
    if (start > last) out.push({ text: line.slice(last, start) });
    const text = m[0];
    const head = text[0];
    if (head === '"' || head === "'" || head === "`") out.push({ text, cls: "text-ok" });
    else if (head === "#" || text.startsWith("//")) out.push({ text, cls: "text-faint italic" });
    else if (/^\d/.test(text)) out.push({ text, cls: "text-warn" });
    else if (KEYWORDS.has(text.toLowerCase())) out.push({ text, cls: "text-accent" });
    else out.push({ text });
    last = start + text.length;
  }
  if (last < line.length) out.push({ text: line.slice(last) });
  return out;
}

function markdownLine(line: string, inFence: boolean): Token[] {
  if (inFence || line.startsWith("```")) return [{ text: line, cls: "text-muted" }];
  if (/^#{1,6}\s/.test(line)) return [{ text: line, cls: "text-accent font-semibold" }];
  const bullet = /^(\s*(?:[-*+]|\d+\.)\s(?:\[[ xX]\]\s)?)(.*)$/.exec(line);
  if (bullet) return [{ text: bullet[1], cls: "text-faint" }, { text: bullet[2] }];
  if (/^>\s?/.test(line)) return [{ text: line, cls: "text-muted italic" }];
  return [{ text: line }];
}

export function highlight(text: string, path: string): Token[][] {
  const lines = text.split("\n");
  if (MARKDOWN_EXT.has(extension(path))) {
    let inFence = false;
    return lines.map((line) => {
      const tokens = markdownLine(line, inFence);
      if (line.startsWith("```")) inFence = !inFence;
      return tokens;
    });
  }
  return lines.map(codeLine);
}
