/**
 * Which tape a number came from, said on the number.
 *
 * `tearsheet/provenance.py::build_stamp` states this as a requirement rather
 * than a preference:
 *
 * > `source` is the one field that changes what the numbers *mean*: "chain" and
 * > "synthetic" are not two qualities of the same result, they are two
 * > different claims, and **the UI is required to say which one it is showing**.
 *
 * The UI stopped. `SourceBanner` carried it on every card and was deleted;
 * nothing replaced it, so `source` reached no view on any card or on
 * `/advantage`, and `AGENT_FIELDS` recorded it as unrendered.
 *
 * `tests/web/test_source_disclosure.py` is about exactly this failure and
 * describes it from the tree where it last happened:
 *
 *     /advantage        Protect — Sentinel   −38.17pp   source: chain
 *     /agent/sentinel   Sentinel             +0.72pp    source: synthetic
 *
 * "A sign flip, one click apart, both pages confident and neither mentioning
 * the other." That test was narrowed to guard the artifact when the component
 * went, and its docstring is honest about the narrowing — but the artifact half
 * was never the half that broke.
 *
 * Today every card reads `chain` and `/advantage`'s short panel reads
 * `synthetic`, disclosed only as "Deliberately short tape". Short and synthetic
 * are different claims: a short *chain* tape is real history that ran out, and
 * a short *synthetic* one is a random walk. One `make showcase-demo` puts the
 * documented failure back with nothing on screen to catch it.
 *
 * ## Never colour alone, and never silent
 *
 * The word is always rendered — `Pill`'s rule, which this inherits. A synthetic
 * tape also carries the warm hatch, because it is the one value that changes
 * what every figure beside it means. An unrecognised value is printed rather
 * than mapped to a default: a source nobody anticipated is exactly the case
 * where guessing is worst.
 */
const TAPE: Record<string, { text: string; tone: string }> = {
  chain: { text: "chain tape", tone: "text-faint" },
  synthetic: {
    text: "synthetic tape",
    tone: "hatched rounded-sm px-1 text-warn [--hatch-tone:var(--hatch-warn)]",
  },
  mixed: {
    text: "mixed tape",
    tone: "hatched rounded-sm px-1 text-warn [--hatch-tone:var(--hatch-warn)]",
  },
  none: { text: "no tape", tone: "text-faint" },
};

export function TapeSource({ source, className = "" }: { source?: string; className?: string }) {
  // Absent is not "chain". An artifact that did not record its tape is a
  // different thing from one that recorded a real one, and the whole argument
  // of the module this reads from is that those must not be conflated.
  if (!source) return null;

  const tape = TAPE[source] ?? { text: `${source} tape`, tone: "text-warn" };

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono text-[11px] leading-none tracking-wide whitespace-nowrap ${tape.tone} ${className}`}
    >
      {tape.text}
    </span>
  );
}
