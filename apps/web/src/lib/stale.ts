import type { BehindEntry } from "@/components/StaleNotice";
import { readArtifact } from "@/lib/build-artifact";

/**
 * Which artifacts were generated before the engine that produced them changed.
 *
 * **Server components only** — it reads from disk through `readArtifact`.
 * Deliberately so: the notice this feeds is a caveat on figures that are
 * themselves prerendered, and one that appeared only after hydration would be
 * absent in the exported HTML, which is the copy a reader with JavaScript off
 * gets and the copy a scraper quotes.
 *
 * Keyed on the presence of `data.behind` rather than on the check's name.
 * `go_no_go.py` owns that string and has reworded its checks before; a page
 * matching on it would fail silently and render nothing, which is the failure
 * mode this whole notice exists to prevent.
 */
interface StatusCheck {
  data?: { behind?: BehindEntry[] };
}

export function artifactsBehindEngine(): BehindEntry[] {
  const status = readArtifact<{ checks?: StatusCheck[] }>("status.json");
  const check = (status?.checks ?? []).find((c) => Array.isArray(c.data?.behind));
  return check?.data?.behind ?? [];
}
