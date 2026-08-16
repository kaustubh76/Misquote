/**
 * There is no "bad" tone, and that is a claim rather than an omission.
 *
 * One existed and was never used, which is the correct outcome arrived at by
 * accident. A badge qualifies a number — "counterfactual", "synthetic tape" —
 * and a qualification is not a failure. The things that *can* fail here are
 * verdicts, and those render as `Pill`, which does have a red. Restoring a red
 * badge would let a caller mark a standing caveat as an error in a colour that
 * means something else two components over.
 */
type BadgeTone = "warn" | "neutral";

const TONE: Record<BadgeTone, string> = {
  warn: "border-warn text-warn",
  neutral: "border-neutral-line text-dim",
};

/**
 * A standing qualification on everything below it.
 *
 * `scripts/showcase.py` puts it well: the badge "is not a disclaimer bolted on
 * at the end. It is a field on the artifact, asserted by a test, and the web
 * app renders it as prominently as the number it qualifies." So it is never
 * derived here — it is read from the artifact and displayed.
 */
export function Badge({
  children,
  tone = "warn",
}: {
  children: React.ReactNode;
  tone?: BadgeTone;
}) {
  return (
    <span
      className={`inline-block rounded-sm border px-2 py-1 font-mono text-[11px] leading-none font-semibold tracking-wider uppercase ${TONE[tone]}`}
    >
      {children}
    </span>
  );
}
