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
/**
 * One entry per `Source`, exhaustive by type rather than by a boolean.
 *
 * This was `const live = source === "live"` with an `else` — which is correct
 * for two states and silently wrong for three: a simulated answer would have
 * fallen into the `else` and rendered "recorded earlier", the one phrase it
 * must not wear. It would have typechecked, and the whole design of the
 * simulated source is that its label cannot be wrong.
 *
 * `Record<Source, …>` makes a fourth state a type error at the moment it is
 * added, which is the only moment anyone is thinking about it.
 *
 * The mark is a filled dot for live, a hollow one for recorded, and the neutral
 * hatch for simulated — `--hatch-none`, this site's texture for "there was
 * never anything here" (`Ledger.tsx`), which is exactly true of a response
 * nobody computed. Never colour alone: the word is present in all three cases,
 * the rule `Pill` sets and this inherits.
 */
const ANSWER: Record<Source, { text: string; tone: string; dot: string }> = {
  live: { text: "answered live", tone: "text-dim", dot: "border-good bg-good" },
  artifact: { text: "recorded earlier", tone: "text-faint", dot: "border-neutral-line" },
  simulated: {
    text: "simulated",
    tone: "text-warn",
    dot: "border-warn-line hatched [--hatch-tone:var(--hatch-none)]",
  },
};

export function AnsweredBy({ source, className = "" }: { source: Source; className?: string }) {
  const answer = ANSWER[source];

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono text-[11px] leading-none tracking-wide whitespace-nowrap ${answer.tone} ${className}`}
    >
      <span
        aria-hidden="true"
        className={`inline-block h-1.5 w-1.5 rounded-full border ${answer.dot}`}
      />
      {/* Spelled out rather than "live"/"cached". The reader's question is not
          which transport was used, it is whether anyone computed this for them
          — and "recorded" is the same word the artifacts use for themselves. */}
      {answer.text}
    </span>
  );
}
