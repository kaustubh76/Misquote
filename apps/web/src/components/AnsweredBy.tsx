import type { Source } from "@/lib/api";

/**
 * Which of the two things answered: a running service, or a file on disk.
 *
 * `loadLive` has returned this since it was written — "`source` is returned
 * rather than inferred so the UI can say which it got" — and for the life of
 * that sentence no UI said it.
 *
 * ## Why this is inline rather than a page-level strip
 *
 * This qualifies one answer the reader just asked for, not the page. It says
 * whether *that* answer was computed just now or read from a snapshot, which
 * changes how fresh it is — and freshness belongs beside the number rather than
 * above the page.
 *
 * ## Never colour alone
 *
 * The dot is filled for live and hollow for recorded, and the word is present
 * in both cases — the rule `Pill` states and this inherits. A reader who cannot
 * see the tone still has the shape and the text.
 */
export function AnsweredBy({ source, className = "" }: { source: Source; className?: string }) {
  const live = source === "live";

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono text-[11px] leading-none tracking-wide whitespace-nowrap ${
        live ? "text-dim" : "text-faint"
      } ${className}`}
    >
      <span
        aria-hidden="true"
        className={`inline-block h-1.5 w-1.5 rounded-full border ${
          live ? "border-good bg-good" : "border-neutral-line"
        }`}
      />
      {/* Spelled out rather than "live"/"cached". The reader's question is not
          which transport was used, it is whether anyone computed this for them
          — and "recorded" is the same word the artifacts use for themselves. */}
      {live ? "answered live" : "recorded earlier"}
    </span>
  );
}
