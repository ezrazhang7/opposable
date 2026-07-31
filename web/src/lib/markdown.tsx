import type { ReactNode } from "react";

/** A minimal markdown renderer for agent-written prose (task summaries and
 *  file previews). It builds React nodes directly — no HTML string is ever
 *  constructed, so there is nothing to sanitise — and it covers only what the
 *  model actually writes: headings, lists, fenced code, quotes, emphasis,
 *  inline code and links. Anything it does not recognise stays literal text.
 */

const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)|(\[[^\]]+\]\([^)\s]+\))|(https?:\/\/\S+)/g;

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const m of text.matchAll(INLINE)) {
    const start = m.index ?? 0;
    if (start > last) out.push(text.slice(last, start));
    const token = m[0];
    const key = `${keyBase}-${n++}`;
    if (token.startsWith("`")) {
      out.push(
        <code key={key} className="rounded bg-raised px-1 py-0.5 font-mono text-[0.92em]">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**")) {
      out.push(
        <strong key={key} className="font-semibold">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("*")) {
      out.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith("[")) {
      const split = token.indexOf("](");
      const label = token.slice(1, split);
      const href = token.slice(split + 2, -1);
      out.push(
        <a
          key={key}
          href={href}
          target="_blank"
          rel="noreferrer"
          className="text-accent underline underline-offset-2"
        >
          {label}
        </a>,
      );
    } else {
      out.push(
        <a
          key={key}
          href={token}
          target="_blank"
          rel="noreferrer"
          className="text-accent underline underline-offset-2"
        >
          {token}
        </a>,
      );
    }
    last = start + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const QUOTE = /^>\s?(.*)$/;

export function Markdown({ text, className }: { text: string; className?: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let fence: { lang: string; body: string[] } | null = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const body = paragraph.join(" ");
    blocks.push(
      <p key={`p${blocks.length}`} className="my-2 first:mt-0 last:mb-0">
        {inline(body, `p${blocks.length}`)}
      </p>,
    );
    paragraph = [];
  };

  const flushList = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    const key = `l${blocks.length}`;
    blocks.push(
      <Tag
        key={key}
        className={`my-2 space-y-1 pl-5 ${list.ordered ? "list-decimal" : "list-disc"} marker:text-faint`}
      >
        {list.items.map((item, i) => (
          <li key={i}>{inline(item, `${key}-${i}`)}</li>
        ))}
      </Tag>,
    );
    list = null;
  };

  for (const line of lines) {
    if (fence) {
      if (line.startsWith("```")) {
        blocks.push(
          <pre
            key={`c${blocks.length}`}
            className="my-2 overflow-x-auto rounded-xl border border-line bg-raised px-3 py-2 font-mono text-[12px] whitespace-pre"
          >
            {fence.body.join("\n")}
          </pre>,
        );
        fence = null;
      } else {
        fence.body.push(line);
      }
      continue;
    }
    if (line.startsWith("```")) {
      flushParagraph();
      flushList();
      fence = { lang: line.slice(3).trim(), body: [] };
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      const size = level <= 1 ? "text-[16px]" : level === 2 ? "text-[14.5px]" : "text-[13.5px]";
      blocks.push(
        <p key={`h${blocks.length}`} className={`mt-3 mb-1 font-semibold first:mt-0 ${size}`}>
          {inline(heading[2], `h${blocks.length}`)}
        </p>,
      );
      continue;
    }

    const quote = QUOTE.exec(line);
    if (quote) {
      flushParagraph();
      flushList();
      blocks.push(
        <p
          key={`q${blocks.length}`}
          className="my-2 border-l-2 border-line pl-3 text-muted italic"
        >
          {inline(quote[1], `q${blocks.length}`)}
        </p>,
      );
      continue;
    }

    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const ordered = Boolean(numbered);
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push((bullet ?? numbered)![1]);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    flushList();
    paragraph.push(line.trim());
  }

  if (fence) {
    blocks.push(
      <pre
        key={`c${blocks.length}`}
        className="my-2 overflow-x-auto rounded-xl border border-line bg-raised px-3 py-2 font-mono text-[12px] whitespace-pre"
      >
        {fence.body.join("\n")}
      </pre>,
    );
  }
  flushParagraph();
  flushList();

  return <div className={className}>{blocks}</div>;
}
