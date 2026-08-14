import { Fragment } from "react";
import { WithCitations } from "@/components/Cite";

export type Block =
  | { type: "p"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "code"; text: string }
  | { type: "table"; head: string[]; rows: string[][] };

/**
 * Inline markdown: bold, emphasis, code — and assumption citations.
 *
 * Rendered as React elements rather than assembled into an HTML string, so
 * document text never reaches `dangerouslySetInnerHTML`. These blocks come from
 * markdown files in the repo rather than from a user, but the escaping bug that
 * pattern invites does not care where the text came from, and the old page's
 * hand-rolled `esc()` did not escape apostrophes.
 */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g).filter(Boolean);

  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={i} className="text-ink">
              <WithCitations text={part.slice(2, -2)} />
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
            <em key={i}>
              <WithCitations text={part.slice(1, -1)} />
            </em>
          );
        }
        return <WithCitations key={i} text={part} />;
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
                <Inline text={block.text} />
              </p>
            );

          case "ul":
            return (
              <ul key={i} className="my-3 list-disc space-y-1.5 pl-5 text-sm text-dim">
                {block.items.map((item, j) => (
                  <li key={j}>
                    <Inline text={item} />
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
                className="my-3 overflow-x-auto rounded-sm border border-line bg-panel-2 p-3 font-mono text-xs text-dim"
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
                          <Inline text={cell} />
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
                            <Inline text={cell} />
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
