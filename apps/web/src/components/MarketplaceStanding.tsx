import { Pill } from "@/components/Pill";
import { count } from "@/lib/format";

/**
 * What this project is on TermiX, as opposed to what it has read about TermiX.
 *
 * The block above this one publishes their protocol: the contracts, the escrow
 * interface recovered from bytecode, how many of its selectors resolve. All of
 * it is a reading. None of it says whether these agents can be hired there, and
 * for a long time the answer was no in a way nothing on this site admitted —
 * five agents indexed among 340,954 ERC-8004 mints, `services: []`, and no way
 * for anybody to buy anything.
 *
 * ## The counter that is still zero is the reason this block exists
 *
 * Four things happened and a fifth did not. `activeOrders` is 0: an autonomous
 * agent bid on our brief, we accepted, and the escrow transaction has never
 * been sent. The campaign is `DRAFT` for the same reason — its reward is
 * unfunded.
 *
 * A block that showed three published listings, a bid, a brief and a bounty and
 * left that out would read as a completed trade. So `not_done` is rendered at
 * the same weight as the rest, and the counters are shown **against their
 * baseline**, because "it is not zero" is a claim about a change and one
 * reading cannot carry it.
 */
export interface Participation {
  listings?: {
    agent: string;
    erc8004_token_id?: string | null;
    listing_id?: string | null;
    status?: string | null;
    price_usdc?: string | null;
    title?: string | null;
    proved_by?: string | null;
  }[];
  counters?: {
    baseline?: Counters | null;
    now?: Counters | null;
  };
  brief?: { id?: string | null; status?: string | null; quotes?: number | null; budget_usdc?: string | null };
  bid?: {
    offer_id?: string | null;
    on_brief?: string | null;
    brief_status?: string | null;
    price_usdc?: string | null;
  };
  bounty?: {
    id?: string | null;
    status?: string | null;
    reward_usdc?: string | null;
    funded_tx?: string | null;
  };
  inbound_offer?: {
    offer_id?: string | null;
    checkout_id?: string | null;
    checkout_status?: string | null;
  };
  /** One sentence per thing still outstanding, derived from the platform's own
   *  state rather than written down — a hand-kept status stays true until it
   *  silently does not, which it did for the minutes between the escrow mining
   *  and somebody rereading the prose. Empty means nothing is outstanding. */
  not_done?: string[] | null;
  orders?: {
    order_id?: string | null;
    status?: string | null;
    budget?: string | null;
    currency?: string | null;
    chain_order_id?: string | null;
  }[];
  refused?: Record<string, string>;
  reason?: string | null;
}

interface Counters {
  activeOrders?: number | null;
  openBriefs?: number | null;
  savedListings?: number | null;
  campaignsTotal?: number | null;
}

/** The four the dashboard leads with, in the order it shows them. */
const SHOWN: { key: keyof Counters; label: string }[] = [
  { key: "activeOrders", label: "Orders" },
  { key: "openBriefs", label: "Requests" },
  { key: "campaignsTotal", label: "Bounties" },
  { key: "savedListings", label: "Saved" },
];

function Delta({ from, to }: { from?: number | null; to?: number | null }) {
  const moved = typeof to === "number" && to > (from ?? 0);
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="tabular font-mono text-faint">{count(from ?? 0)}</span>
      <span aria-hidden="true" className="text-faint">
        →
      </span>
      <span className={`tabular font-mono ${moved ? "text-ink" : "text-faint"}`}>
        {count(to ?? 0)}
      </span>
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm">
      <span className="text-dim">{label}</span>
      <span className="min-w-0 text-right text-ink">{children}</span>
    </div>
  );
}

export function MarketplaceStanding({ p }: { p: Participation }) {
  if (p.reason) {
    return <p className="mt-5 mb-0 border-t border-line pt-4 text-xs text-faint">{p.reason}</p>;
  }
  const listings = p.listings ?? [];
  const base = p.counters?.baseline ?? {};
  const now = p.counters?.now ?? {};

  return (
    <div className="mt-5 border-t border-line pt-4">
      <p className="m-0 text-sm text-dim">
        And what we are <em>on</em> it, rather than what we have read about it.
      </p>

      {/* The dashboard's own four, each against where it started. */}
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {SHOWN.map(({ key, label }) => (
          <div key={key} className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-dim">{label}</span>
            <Delta from={base[key]} to={now[key]} />
          </div>
        ))}
      </div>

      {listings.length > 0 && (
        <ul className="mt-4 mb-0 grid list-none gap-1.5 p-0">
          {listings.map((row) => (
            /* `min-w-0` on the row, and it is the half that mattered. The
               `ul` above is a grid, so each `li` is a grid item with an implicit
               `min-width: auto` — it refuses to shrink below its own min-content
               width, and the `truncate` span below makes that min-content the
               full unwrapped title. Constraining only the span left the row at
               436px inside a 300px parent and the page 91px too wide at 390. */
            <li
              key={row.listing_id}
              className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-xs"
            >
              <span className="font-mono text-ink">{row.agent}</span>
              <Pill tone={row.status === "PUBLISHED" ? "pass" : "none"}>
                {row.status?.toLowerCase()}
              </Pill>
              <span className="tabular font-mono text-dim">${row.price_usdc}</span>
              {/* `flex-1` matters as much as `min-w-0`. `truncate` sets
                  `white-space: nowrap`, so on a wrapped row this span goes onto
                  a line of its own and then sizes to its full unwrapped text —
                  436px inside a 300px parent, and 91px of horizontal overflow
                  on the whole document at 390px. A flex basis of 0 makes it
                  take the line it is on rather than the width it wants. */}
              <span className="min-w-0 flex-1 truncate text-faint">{row.title}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 grid gap-2 border-t border-line pt-3">
        {p.bid?.offer_id && (
          <Row label="Bid on somebody else's request">
            <span className="tabular font-mono">${p.bid.price_usdc}</span>{" "}
            <span className="text-faint">· that request is now </span>
            <span className="font-mono text-dim">{p.bid.brief_status?.toLowerCase()}</span>
          </Row>
        )}
        {p.brief?.id && (
          <Row label="Our own request">
            <span className="tabular font-mono">${p.brief.budget_usdc}</span>{" "}
            <span className="text-faint">
              · {count(p.brief.quotes ?? 0)} quote{p.brief.quotes === 1 ? "" : "s"} ·{" "}
            </span>
            <span className="font-mono text-dim">{p.brief.status?.toLowerCase()}</span>
          </Row>
        )}
        {p.bounty?.id && (
          <Row label="Bounty we sponsor">
            <span className="tabular font-mono">${p.bounty.reward_usdc}</span>{" "}
            <span className="text-faint">· </span>
            <span className="font-mono text-dim">{p.bounty.status?.toLowerCase()}</span>
            {!p.bounty.funded_tx && <span className="text-faint"> · unfunded</span>}
          </Row>
        )}
        {(p.orders ?? []).map((o) => (
          <Row key={o.order_id} label="Order, escrowed">
            <span className="tabular font-mono">
              ${o.budget} {o.currency}
            </span>{" "}
            <span className="text-faint">· </span>
            <span className="font-mono text-dim">{o.status?.toLowerCase()}</span>
            {o.chain_order_id && (
              <span className="mt-0.5 block font-mono text-xs break-all text-faint">
                {o.chain_order_id}
              </span>
            )}
          </Row>
        ))}
        {p.inbound_offer?.checkout_id && (
          <Row label="Offer made to us">
            <span className="font-mono text-dim">
              {p.inbound_offer.checkout_status?.toLowerCase()}
            </span>
          </Row>
        )}
      </div>

      {/* The half that has not happened, at the same weight as the half that
          has. Without it this block is a run of completed things and a silence. */}
      {p.not_done && p.not_done.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <p className="m-0 text-sm">
            <strong className="text-warn">Not done.</strong>
          </p>
          <ul className="mt-1 mb-0 grid list-none gap-1 p-0">
            {p.not_done.map((why) => (
              <li key={why} className="min-w-0 max-w-[72ch] text-sm break-words text-dim">
                {why}
              </li>
            ))}
          </ul>
        </div>
      )}

      {p.refused && Object.keys(p.refused).length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-faint">
            Why {count(Object.keys(p.refused).length)} were not listed
          </summary>
          <ul className="mt-2 mb-0 grid list-none gap-2 p-0">
            {Object.entries(p.refused).map(([agent, why]) => (
              <li key={agent} className="max-w-[72ch] text-xs text-faint">
                <span className="font-mono text-dim">{agent}</span> — {why}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
