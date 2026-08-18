export type PillTone = "pass" | "fail" | "none" | "unverified" | "info";

const TONE: Record<PillTone, { cls: string; glyph: string; word: string }> = {
  pass: { cls: "bg-good-bg text-good border-good-line", glyph: "✓", word: "Pass" },
  fail: { cls: "bg-bad-bg text-bad border-bad-line", glyph: "✕", word: "Fail" },
  none: { cls: "bg-neutral-bg text-neutral border-neutral-line", glyph: "—", word: "No verdict" },
  unverified: { cls: "bg-warn-bg text-warn border-warn-line", glyph: "?", word: "Unverified" },
  info: { cls: "bg-neutral-bg text-dim border-neutral-line", glyph: "·", word: "Note" },
};

/**
 * A verdict, carrying its meaning three ways: shape, glyph, and word.
 *
 * The page this replaces distinguished pass from fail with `color: var(--good)`
 * against `color: var(--bad)` and nothing else, so for a red-green colourblind
 * reader — and for anyone printing it — the two states were identical. Colour
 * here is the third signal, never the only one.
 *
 * There is deliberately no `title`. It carried each verdict's *reason* — the
 * threshold and the sample size — on a non-focusable span, which is announced
 * by almost no screen reader and reachable by neither keyboard nor touch. The
 * reason is the most interesting half of a verdict, so it is rendered as
 * visible text beside the pill instead.
 */
export function Pill({ tone, children }: { tone: PillTone; children?: React.ReactNode }) {
  const t = TONE[tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${t.cls}`}
    >
      <span aria-hidden="true" className="font-mono">
        {t.glyph}
      </span>
      {children ?? t.word}
    </span>
  );
}

/** Map a Python `Verdict` onto a tone. An uncalled verdict is never a failure. */
export function verdictTone(verdict: { called: boolean; label: string }): PillTone {
  if (!verdict.called) return "none";
  if (verdict.label.startsWith("PASS")) return "pass";
  if (verdict.label.startsWith("FAIL")) return "fail";
  return "info";
}

/**
 * The tone for a readiness-gate status, which is a different vocabulary.
 *
 * `verdictTone` above reads a `{called, label}` object — the shape a quote
 * carries. A gate in `status.json` is a bare string: PASS, FAIL, UNVERIFIED.
 * The two are not interchangeable and a caller with the wrong one gets a type
 * error rather than a plausible tone.
 *
 * This lived privately in `status/view.tsx`, which was fine while one page read
 * gate statuses. It is here the moment a second one does, because the mapping
 * that matters is UNVERIFIED to amber — "we could not check this" is not "this
 * failed" and is never green — and two copies of that rule is one copy too
 * many.
 *
 * An unrecognised status is `"unverified"`, not `"pass"`. A status nobody
 * anticipated is by definition one nothing has checked.
 */
export function statusTone(status: string): PillTone {
  if (status === "PASS") return "pass";
  if (status === "FAIL") return "fail";
  return "unverified";
}
