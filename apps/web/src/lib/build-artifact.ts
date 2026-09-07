import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * An artifact, read from disk while the site is being built.
 *
 * **Server components only.** This imports `node:fs`; a `"use client"` module
 * that pulls it in is a defect, and `tests/web/test_client_boundary.py` is what
 * says so.
 *
 * ## Why the boundary needs a guard rather than care
 *
 * `lib/routes.ts` records the mirror-image mistake — importing a value out of a
 * client module into a server one — and notes that it fails at prerender rather
 * than at typecheck, with `TypeError: g.LINKS.map is not a function`. Loud, and
 * findable.
 *
 * This direction is quieter, and the `try/catch` below is why. Pulled into a
 * client graph, this does not throw: it returns `undefined`, every page seeded
 * from it falls back to its spinner, the fetch covers for it a moment later, and
 * the build stays green. The property would be gone and nothing would say so —
 * which is exactly how the export came to render no numbers for months.
 *
 * ## Why a miss is not an error
 *
 * A missing artifact is a state this site renders on purpose: "nothing has
 * generated the cards yet, run `make showcase-demo`". The client load owns that
 * path, and it is where the remedy text and the tests already live. Throwing
 * here would replace a page that tells a reader what to run with a build that
 * fails at them instead.
 *
 * The value is a *first paint*, never the truth. Every view that takes one keeps
 * its `useEffect`, so the fetch overwrites it — which is what preserves the
 * promise the agent route has carried since it was written: editing a JSON and
 * reloading still works.
 */
export function readArtifact<T>(name: string): T | undefined {
  const path = join(process.cwd(), "public", "artifacts", name);
  try {
    return JSON.parse(readFileSync(path, "utf8")) as T;
  } catch {
    return undefined;
  }
}

/**
 * Every scenario fixture on disk, read while the site is being built.
 *
 * **Server components only**, for the reason above.
 *
 * The list is *derived from the directory* rather than written down, which is
 * the same discipline the not-built ledger uses: a fixture that exists and is
 * not listed, or a name listed and long since deleted, are both states nobody
 * would notice. `/demo` renders whatever is here, so adding a fixture publishes
 * it and deleting one un-publishes it.
 *
 * The `label`/`why` requirement is not this function's invention — `scenario.ts`
 * already refuses to honour a fixture missing either, on the grounds that "a
 * file that does not describe itself is not a scenario". Applying the same bar
 * here keeps `/demo` from advertising a name the loader will decline.
 */
export interface ScenarioSummary {
  name: string;
  label: string;
  why: string;
  /** The API paths it answers for, so the page can say what it covers. */
  paths: string[];
  /**
   * Where this state is worth looking at.
   *
   * Carried by the fixture rather than derived from its paths: a fixture
   * stubbing `/quote/eligibility/{address}` could belong on `/quote` or on a
   * wallet page that does not exist, and guessing would send a reader somewhere
   * the state does not appear.
   */
  route: string;
}

export function readScenarios(): ScenarioSummary[] {
  const dir = join(process.cwd(), "public", "scenarios");
  let names: string[];
  try {
    names = readdirSync(dir).filter((f) => f.endsWith(".json"));
  } catch {
    return [];
  }

  const found: ScenarioSummary[] = [];
  for (const file of names.sort()) {
    try {
      const body = JSON.parse(readFileSync(join(dir, file), "utf8"));
      if (typeof body?.label !== "string" || typeof body?.why !== "string") continue;
      found.push({
        name: file.replace(/\.json$/, ""),
        label: body.label,
        why: body.why,
        paths: Object.keys(body.responses ?? {}),
        route: typeof body.route === "string" ? body.route : "",
      });
    } catch {
      // A malformed fixture is one the loader would refuse too. Skipping it
      // here shows the reader the same set the site can actually serve.
      continue;
    }
  }
  return found;
}

/**
 * What hiring an agent costs, read at build time from the two artifacts that
 * record it.
 *
 * Shared rather than duplicated: the landing page and each category page both
 * render `AgentCard`, and a second copy of this join is a second thing to go
 * stale — the trap `studio_report.py` fell into with its own hand-written copy
 * of the ledger.
 *
 * Neither half is typed. The opening escrow is what the recorded mainnet hire
 * actually escrowed; the fee is the keystore's own `getRegistrationFeeInWei()`
 * plus the measured gas of a grant and a revoke, which the advantage report
 * already carries on every task.
 */
export interface HireTermsRead {
  opening_budget: number | null;
  budget_decimals: number | null;
  fee_bnb: number | null;
}

export function readHireTerms(): HireTermsRead | undefined {
  const registry = readArtifact<{
    hire_flow?: {
      mainnet_proof?: { budget?: number; chain_id?: number };
      deployments?: Record<string, { decimals?: number }>;
    };
  }>("registry.json");
  const advantage = readArtifact<{
    tasks?: { hire_cost?: { amount?: number } }[];
  }>("advantage.json");

  const budget = registry?.hire_flow?.mainnet_proof?.budget;
  // One hire, not one per task, so every task carries the same fee and the
  // first that has one is the figure. A report with none yields nothing here
  // rather than a zero.
  const fee = advantage?.tasks?.find((t) => typeof t.hire_cost?.amount === "number")?.hire_cost
    ?.amount;
  if (typeof budget !== "number" && typeof fee !== "number") return undefined;

  // The token's decimals, read off chain by `verify_erc8183.py` and carried
  // through `registry.json`. This was the literal `18`, under a comment
  // approving of `chain/addresses.py` for reading rather than assuming — the
  // wrong way round, on the one figure where that mistake is expensive: BSC's
  // USDT is 18 where Ethereum's is 6, and guessing misprices by twelve orders
  // of magnitude. It is the same defect the escrow console was fixed for this
  // morning, reintroduced one file over.
  //
  // From the chain the recorded hire ran on, so the scale belongs to the token
  // the budget is denominated in. Absent when unread, and `HirePrice` then
  // shows the fee alone rather than an amount at a guessed scale.
  const chain = registry?.hire_flow?.mainnet_proof?.chain_id;
  const decimals =
    chain === undefined ? undefined : registry?.hire_flow?.deployments?.[String(chain)]?.decimals;

  return {
    opening_budget: typeof budget === "number" ? budget : null,
    budget_decimals: typeof decimals === "number" ? decimals : null,
    fee_bnb: typeof fee === "number" ? fee : null,
  };
}
