import { Heading } from "@/components/Heading";
import { WithCitations } from "@/components/Cite";
import { Pill, type PillTone } from "@/components/Pill";
import { Refusal } from "@/components/Refusal";

export interface CheckRow {
  name: string;
  status: string;
  detail: string;
  provenance: string;
}

const TONE: Record<string, PillTone> = {
  PASS: "pass",
  FAIL: "fail",
  WARN: "unverified",
};

/**
 * A list of named checks, each with the reading that produced it.
 *
 * Extracted so that `/vetting` can render two subjects with one renderer:
 * pools, badged by `misquote/vetting/badge.py`, and the contract addresses the
 * signer is aimed at, checked by `misquote/vetting/addresses.py`. Both produce
 * `{name, status, detail, provenance}` against the same `PASS/WARN/FAIL/UNKNOWN`
 * vocabulary, which is not a coincidence — they are the same question asked
 * about two different subjects, and sharing the renderer is the argument that
 * they really are. If the two could not share it, they were not the same shape
 * and the page should not have implied they were.
 *
 * **`UNKNOWN` is a `Refusal`, not a red pill.** The read did not happen, so
 * there is no finding to colour. `badge.Check.blocking` treats it as blocking
 * all the same — an address nobody could check and an address checked clean
 * must never render alike — but blocking a verdict and being a failure are
 * different claims, and only one of them is true here.
 */
export function CheckList({ checks }: { checks: CheckRow[] }) {
  // A filtered-out subject says so, rather than rendering an empty <ul>.
  //
  // `/vetting` narrows every subject on the page with one control, and a
  // subject with no match rendered a live heading over nothing — no message, no
  // count, no indication the filter was the reason. Silence there reads as "we
  // checked and found nothing to show", which on this page is a different and
  // much stronger claim than "your filter excluded these".
  //
  // Not a `Refusal`: nothing was refused and no evidence fell short. It is the
  // reader's own filter, and the sentence says so.
  if (checks.length === 0) {
    return (
      <p className="m-0 text-sm text-dim">No checks here match the current filter.</p>
    );
  }

  return (
    <ul className="m-0 list-none space-y-4 p-0">
      {checks.map((check) =>
        check.status === "UNKNOWN" ? (
          <li key={check.name}>
            <Refusal title={check.name} reason={check.detail} floor={check.provenance} />
          </li>
        ) : (
          <li key={check.name} className="border-l-2 border-line pl-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              {/* Explicitly h4. `Card` cannot provide a level — `CardHeader`
                  arrives as a child, so the card never knows whether it has a
                  title. Without this, each check is a sibling of the verdict it
                  is the evidence for. The escape hatch exists for exactly this,
                  and using it is visible in a diff. */}
              <Heading level={4} className="m-0 text-sm font-semibold">
                {check.name}
              </Heading>
              <Pill tone={TONE[check.status] ?? "info"}>{check.status}</Pill>
            </div>
            <p className="mt-1 mb-0 font-mono text-xs break-words text-dim">{check.detail}</p>
            <p className="mt-1 mb-0 text-xs text-faint">
              {/* Provenance cites matrix items, so P-6 and V-10 become links
                  into /assumptions rather than inert text. */}
              <WithCitations text={check.provenance} />
            </p>
          </li>
        ),
      )}
    </ul>
  );
}
