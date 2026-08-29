import { timestamp } from "@/lib/format";

/**
 * Which engine produced this number, beside the number.
 *
 * ## The contradiction this is for
 *
 * `make showcase` rewrites the three LP cards. Router's card comes from `make
 * router-card` and the advantage report from `make advantage`, so running the
 * first alone leaves the site publishing two answers about one agent:
 * `/advantage` said Warden loses to DIY by 64.29pp while `/agent/warden` said
 * it beats DIY by 17.21pp — eighty-one points apart, from two runs five days
 * and nine engine commits apart.
 *
 * Neither page showed anything. Both numbers were correctly derived, and the
 * only thing separating them — the commit each was computed at — was in both
 * artifacts and rendered by nothing. `tests/web/test_artifact_agreement.py`
 * now fails on that state; this is the same fact where a reader meets it.
 *
 * ## Not the component that was removed
 *
 * `BuildStamp` was a page footer on `/`, `/vetting` and `/registry`, and it was
 * deleted deliberately in `62f6c36`. This is not it coming back. That one said
 * where a *page* came from, once per page; this says where a *number* came
 * from, beside each one — which is the distinction the contradiction turns on,
 * because the two figures sat on different pages and a page-level footer would
 * have stamped each of them correctly and still shown a reader nothing.
 *
 * What is kept from it is the argument about the dirty flag, which was right:
 * "a dirty tree is the qualification that matters most here, because it is the
 * one that makes the sha a lie" — the commit is real and the code that produced
 * the number is not in it. It is `true` on every artifact this repository
 * currently publishes.
 *
 * Not styled as a fault, for the reason that component also gave: regenerating
 * from a working tree is normal and often unavoidable, and the requirement is
 * that it be said rather than prevented.
 *
 * Distinct from `TapeSource`, which sits in the same cards: that says which
 * *tape* the numbers were computed over, this says which *engine* computed
 * them. Two runs can share a tape and disagree, which is exactly what happened.
 */
export function EngineStamp({
  sha,
  generatedAt,
  dirty,
  className = "",
}: {
  sha?: string | null;
  generatedAt?: string | null;
  dirty?: boolean | null;
  className?: string;
}) {
  // Nothing rather than a placeholder. An artifact with no stamp cannot be
  // placed against this history at all, and `go_no_go.check_artifact_freshness`
  // already answers UNVERIFIED for exactly that case — inventing a dash here
  // would put a mark on the page for a fact nobody has.
  if (!sha && !generatedAt) return null;

  return (
    <p className={`m-0 font-mono text-xs break-words text-faint ${className}`}>
      engine {sha ?? "unrecorded"}
      {dirty ? " · uncommitted changes" : ""}
      {generatedAt ? ` · ${timestamp(generatedAt)}` : ""}
    </p>
  );
}
