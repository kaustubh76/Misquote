import type { Source } from "@/lib/api";

/**
 * Which of the two things answered: a running service, or a file on disk.
 *
 * `loadLive` has returned this since it was written — "`source` is returned
 * rather than inferred so the UI can say which it got" — and for the life of
 * that sentence no UI said it. Every `.source` elsewhere in `src/` is the
 * artifact's own `chain`/`synthetic` field, which is a different question
 * entirely, so the capability read as wired while being connected to nothing.
 *
 * ## Why this is not `SourceBanner`
 *
 * They answer independent questions and the states multiply rather than
 * collapse. `SourceBanner` says whether the *tape* is chain history or a
 * stand-in; this says whether the *answer* was computed just now or read from a
 * snapshot. A live answer over a synthetic tape is a real combination, and so
 * is a recorded answer over chain history — the second is what every evidence
 * page on this site shows. Folding the two into one strip would force a reader
 * to disentangle them from a single sentence.
 *
 * It is also the reason this is small and inline while `SourceBanner` is a
 * full-width block at the top of a page. A synthetic tape changes what every
 * number below it means. Where the number was fetched from does not; it changes
 * how fresh it is, which belongs beside the number rather than above the page.
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
