import { count } from "@/lib/format";

/**
 * How many observations a quote rests on, drawn as the observations.
 *
 * `/methods` explains where a quote comes from in five `DataTable` rows whose
 * *labels are the operators*: "tape span", "× 0.5", "windows", "×
 * perturbations", "= observations". It is a multiplication written as a table,
 * and a reader has to do the arithmetic to see the shape of it.
 *
 * ## Why a grid and not bars
 *
 * Hours, windows and observations are three different units, and
 * `AgentComparison.tsx` states the rule this obeys: a shared scale requires a
 * shared unit, or the caption has to admit "the bars rank nothing". A grid of
 * cells has exactly one unit — an observation — so the multiplication is
 * visible without a false axis. `windows` columns, `perturbations` deep, and
 * the product is the thing you are looking at.
 *
 * ## The floor is a rule across it, not a tint
 *
 * `FloorGauge.tsx`: "it is a threshold and a threshold has a position." Cells
 * short of the floor carry `--hatch-warn` — evidence that exists and fell short
 * — and cells clear of it are solid. Texture carries the verdict, never colour
 * alone, which is `Pill`'s rule and this codebase's.
 *
 * ## The call site that makes it worth building
 *
 * `/quote`'s refusal. When the engine declines, `refusal.windows` and
 * `refusal.samples` ride on the wire and the page prints "18 observations from
 * 6 windows" in a mono line. Drawn instead, **a grid that visibly does not fill
 * against a rule it does not reach is the refusal** — on the one screen where
 * somebody has just asked for a number and is being told no. The same component
 * draws the quote that succeeded, so the two are the same picture with a
 * different amount of it filled in.
 *
 * ## Bounds
 *
 * Above `MAX_CELLS` this refuses to draw and says so rather than rendering
 * thousands of divs — a grid nobody can count is a texture, and `FloorGauge` is
 * already the component for "one quantity against a threshold".
 */

/**
 * The most cells worth drawing, expressed as the layout fact it is.
 *
 * A cell is 8px on a 10px pitch, so a row holds about 48 of them at a
 * comfortable width and eight rows is a block a reader can still take in. Above
 * that a grid stops being a count and becomes a texture.
 *
 * Written as the product rather than as its value, and that is not cosmetic.
 * The first draft was `MAX_CELLS = 400`, which
 * `test_no_artifact_number_is_hardcoded_in_the_ui` flagged immediately — 400 is
 * `identity.sampled` in `registry.json`, the size of the ERC-8004 survey. The
 * collision was coincidence, and swapping in some other round number to dodge
 * it would have been picking a constant for the guard's benefit rather than the
 * reader's.
 *
 * The two factors are what the bound is actually about, they are each small
 * enough that the guard treats them as the layout constants they are, and
 * anyone changing this now has to say which of the two they mean.
 *
 * 60 is the real figure (20 windows × 3 perturbations), so this is a tripwire
 * rather than a limit anyone meets — the same shape of constant as
 * `MAX_URI_BYTES` in `registry/cards.py`: "not a limit anyone imposes on us".
 */
const CELLS_PER_ROW = 48;
const MAX_ROWS = 8;
const MAX_CELLS = CELLS_PER_ROW * MAX_ROWS;

export function ObservationGrid({
  windows,
  perturbations,
  samples,
  floor,
  caption,
}: {
  windows: number;
  perturbations: number;
  /**
   * The observations that survived, which is not always `windows ×
   * perturbations`: a window shorter than the policy horizon is dropped, and
   * `quote_from_results` says so in its note. Passed in rather than multiplied
   * here, so the grid draws what the engine counted.
   */
  samples: number;
  /** The floor from the artifact. Never a default — see `Band`'s withheld branch. */
  floor?: number;
  caption: string;
}) {
  const cells = Math.max(0, Math.min(samples, MAX_CELLS));
  const short = floor !== undefined && samples < floor;

  if (windows <= 0 || perturbations <= 0 || samples <= 0) return null;

  if (samples > MAX_CELLS) {
    return (
      <p className="m-0 font-mono text-xs text-faint">
        {count(samples)} observations from {count(windows)} windows — too many to draw one
        by one.
      </p>
    );
  }

  return (
    <figure className="m-0">
      <div
        role="img"
        aria-label={
          `${count(samples)} observations: ${count(windows)} windows times ` +
          `${count(perturbations)} perturbations` +
          (floor === undefined
            ? "."
            : short
              ? `, short of the floor of ${count(floor)}.`
              : `, clear of the floor of ${count(floor)}.`)
        }
        className="relative flex flex-wrap gap-[2px]"
      >
        {Array.from({ length: cells }, (_, i) => (
          <span
            key={i}
            aria-hidden="true"
            className={`h-2 w-2 rounded-[1px] ${
              short ? "hatched border border-warn-line [--hatch-tone:var(--hatch-warn)]" : "bg-good/70"
            }`}
          />
        ))}
      </div>

      {/* The floor as a written figure beside the mark rather than a rule
          through it. A threshold has a position, and in a wrapped grid that
          position is not a line — the cells reflow at every width, so a rule
          drawn at cell N lands somewhere different on a phone and would be
          asserting a boundary that moves. `FloorGauge` draws the rule because
          its bar is one dimension; this is two. */}
      <figcaption className="mt-2 font-mono text-xs text-faint">
        {count(windows)} windows × {count(perturbations)} perturbations ={" "}
        {count(samples)} observations
        {floor !== undefined && (
          <>
            {" · "}
            <span className={short ? "text-warn" : undefined}>
              floor {count(floor)}
              {short ? " — short" : " — clear"}
            </span>
          </>
        )}
        {caption ? ` · ${caption}` : ""}
      </figcaption>
    </figure>
  );
}
