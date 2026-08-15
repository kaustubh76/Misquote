import Link from "next/link";
import { Heading } from "@/components/Heading";

/**
 * A refusal to state a number, presented as a result.
 *
 * This is the thesis as a component. `tearsheet.verdict` refuses below thirty
 * observations, `replay.ranges` refuses below twenty usable sub-windows, and
 * `registry.erc8183.escrow_address` refuses because no deployment has been
 * verified. Each of those is the product working, and each would read as a
 * broken page if it were styled like one.
 *
 * So: warn-toned rather than error-toned, the machine's own explanation shown
 * verbatim, and where a floor caused it, the floor is named with its value. It
 * must never be mistaken for a failed fetch — `ErrorNotice` is that, and looks
 * different on purpose.
 */
export function Refusal({
  title,
  reason,
  floor,
  cite,
  children,
}: {
  title: string;
  reason: string;
  floor?: string;
  cite?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-warn-line bg-warn-bg/40 p-4">
      <div className="flex items-baseline gap-2">
        <span aria-hidden="true" className="font-mono text-warn">
          —
        </span>
        <Heading className="m-0 text-sm font-semibold text-warn">{title}</Heading>
      </div>
      <p className="mt-2 mb-0 text-sm text-dim">{reason}</p>
      {floor && <p className="mt-1 mb-0 font-mono text-xs text-faint">{floor}</p>}
      {cite && (
        <p className="mt-2 mb-0 text-xs">
          <Link href={`/assumptions#${cite}`} className="text-warn">
            Why this floor exists → {cite}
          </Link>
        </p>
      )}
      {children}
    </div>
  );
}

/**
 * Something went wrong, as distinct from something being deliberately withheld.
 *
 * Named separately because conflating the two is the failure the old page had:
 * every cause, including "the artifacts were never generated" and "one file
 * 404'd", produced the same sentence and the same remedy.
 */
export function ErrorNotice({
  title,
  detail,
  remedy,
}: {
  title: string;
  detail: string;
  remedy?: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-bad-line bg-bad-bg/40 p-4" role="alert">
      <div className="flex items-baseline gap-2">
        <span aria-hidden="true" className="font-mono text-bad">
          ✕
        </span>
        <Heading className="m-0 text-sm font-semibold text-bad">{title}</Heading>
      </div>
      <p className="mt-2 mb-0 font-mono text-xs break-words text-dim">{detail}</p>
      {remedy && <p className="mt-2 mb-0 text-sm text-dim">{remedy}</p>}
    </div>
  );
}
