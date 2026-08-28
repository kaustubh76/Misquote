import { Fragment } from "react";
import { WithCitations } from "@/components/Cite";

export type Block =
  | { type: "p"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "code"; text: string }
  | { type: "table"; head: string[]; rows: string[][] };

/**
 * Inline markdown: bold, emphasis, code, links — and assumption citations.
 *
 * Rendered as React elements rather than assembled into an HTML string, so
 * document text never reaches `dangerouslySetInnerHTML`. These blocks come from
 * markdown files in the repo rather than from a user, but the escaping bug that
 * pattern invites does not care where the text came from, and the old page's
 * hand-rolled `esc()` did not escape apostrophes.
 *
 * ## Exported, and the rule that comes with it
 *
 * This was private to `Blocks` for as long as `/assumptions` was the only page
 * whose text was written in markdown. It was not. Every emitter in this
 * repository writes prose the same way — the ledger, the caveats, the escrow
 * findings, the status remedies — and six render sites printed the source
 * characters. The Agent Studio ledger card read "**The funding half of this
 * blocker has closed**" with the asterisks on the screen, on the one card here
 * whose whole job is to be read carefully.
 *
 * **Repository prose only.** The line is who wrote the string, not which file
 * it arrives in. A third-party agent's `description` comes from whoever minted
 * that registry card, and one of them is already `**Crypto Research & Analysis
 * AI Agent**` — bidding for bold on our page. This also turns
 * `[label](href)` into an anchor, so pointing it at a stranger's text hands out
 * an arbitrary link on our pages to whoever mints the next card. That is the
 * primitive `erc8004._assert_fetchable` and `scan8004._decode_feedback_uri`
 * both exist to refuse. `ScanAgents.tsx` says the same thing at the call site,
 * and `tests/web/test_third_party_listings.py` fails if it stops being true.
 */
export function Prose({ text, links = true }: { text: string; links?: boolean }) {
  // `links={false}` for prose that is already inside an anchor, and it is a
  // correctness fix rather than a preference. Three assumption titles name
  // another assumption — "A1 is refused at the decision", "fitted and published
  // as G-4" — and the index renders each title inside its own `<a href="#id">`.
  // A `<Cite>` is a link, so those nested one anchor inside another; the HTML
  // parser hoists the inner one out, the server markup and the client tree stop
  // matching, and `/assumptions` threw React #418 on every load. Emphasis, code
  // and the citation *text* all survive — only the anchors are dropped.
  const inline = (part: string) =>
    links ? <WithCitations text={part} /> : <>{part}</>;

  // Links are matched first and kept whole. Without them, `[0x3669…](https://
  // bscscan.com/address/0x3669…)` rendered as literal markdown — the raw
  // brackets and the full URL, in a table cell, on a 390px screen. It was both
  // the ugliest text on the site and the longest unbreakable string on it.
  const parts = text
    .split(/(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g)
    .filter(Boolean);

  return (
    <>
      {parts.map((part, i) => {
        const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
        if (link && !links) return <Fragment key={i}>{link[1]}</Fragment>;
        if (link) {
          const [, label, href] = link;
          const external = /^https?:/.test(href!);
          return (
            <a
              key={i}
              href={href}
              className="break-all"
              {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
            >
              {label}
            </a>
          );
        }
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={i} className="text-ink">
              {inline(part.slice(2, -2))}
            </strong>
          );
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code key={i} className="rounded-sm bg-panel-2 px-1 font-mono text-[0.9em]">
              {part.slice(1, -1)}
            </code>
          );
        }
        if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
          return (
            <em key={i}>{inline(part.slice(1, -1))}</em>
          );
        }
        return <Fragment key={i}>{inline(part)}</Fragment>;
      })}
    </>
  );
}

export function Blocks({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((block, i) => {
        switch (block.type) {
          case "p":
            return (
              <p key={i} className="my-3 text-sm text-dim first:mt-0 last:mb-0">
                <Prose text={block.text} />
              </p>
            );

          case "ul":
            return (
              <ul key={i} className="my-3 list-disc space-y-1.5 pl-5 text-sm text-dim">
                {block.items.map((item, j) => (
                  <li key={j}>
                    <Prose text={item} />
                  </li>
                ))}
              </ul>
            );

          case "code":
            return (
              <pre
                key={i}
                tabIndex={0}
                role="region"
                aria-label="Code sample"
                className="my-3 overflow-x-auto rounded-sm border border-glass-line bg-panel-2/50 p-3 font-mono text-xs text-dim"
              >
                {block.text}
              </pre>
            );

          case "table":
            return (
              <div
                key={i}
                role="region"
                aria-label="Table"
                tabIndex={0}
                className="my-4 overflow-x-auto"
              >
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr>
                      {block.head.map((cell, j) => (
                        <th
                          key={j}
                          scope="col"
                          className="border-b border-line-strong py-1.5 pr-4 text-left font-semibold text-ink last:pr-0"
                        >
                          <Prose text={cell} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, j) => (
                      <tr key={j}>
                        {row.map((cell, k) => (
                          <td
                            key={k}
                            className="border-b border-line py-1.5 pr-4 align-top text-dim last:pr-0"
                          >
                            <Prose text={cell} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );

          default:
            return <Fragment key={i} />;
        }
      })}
    </>
  );
}
