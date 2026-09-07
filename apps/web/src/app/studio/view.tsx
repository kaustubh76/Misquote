"use client";

/**
 * The BNB Agent Studio half of this marketplace, which had no page.
 *
 * Everything on this route existed before this route did. A seller agent
 * scaffolded by the vendor's CLI, 2,208 lines of it, tracked in
 * `studio/misquoterouter`. That agent deployed and serving A2A. An ERC-8004
 * identity minted by `bag erc8004 register` rather than by anything here. A
 * dated probe of what the CLI can do. None of it was rendered anywhere: the
 * words "Agent Studio" appeared in this UI in exactly two places — one bare
 * link in the hero, and a ledger card explaining what had **not** been built.
 *
 * That is the defect `demo/view.tsx` names about the simulation layer and
 * `RegistrySearch.tsx` names about the survey route: built, correct, and wired
 * to no reader. It has now happened three times, so the shape of the remedy is
 * settled — an emitter, an artifact, and a route.
 *
 * ## Why the negotiate button is the top of the page
 *
 * Because it is the only thing here a reader can disprove in ten seconds, and
 * because it is not our claim. Press it and a *different* agent — deployed
 * separately, holding its own key, which this site cannot sign for — returns a
 * quote it has signed. The signature recovers to the wallet that owns the
 * identity below it, and it binds to a contract address this repository
 * recovered from deployed bytecode months before the scaffold existed.
 *
 * A marketplace arguing that other marketplaces cannot be checked should lead
 * with the thing on it that checks hardest.
 *
 * ## Why the button goes through our own API
 *
 * The agent sends no `Access-Control-Allow-Origin`, on either the card or the
 * JSON-RPC root. A browser cannot call it. `api/studio.py` forwards, and says
 * so in its own docstring; the alternative was to render a recorded blob and
 * call it live, which is the misquote.
 *
 * When the API is asleep — a free host that scales to zero — the recorded
 * envelope from `studio.json` is what renders, labelled `recorded earlier` by
 * `AnsweredBy` rather than passed off as fresh.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AnsweredBy } from "@/components/AnsweredBy";
import { Button } from "@/components/Button";
import { Card, CardHeader } from "@/components/Card";
import { CheckList, type CheckRow } from "@/components/CheckList";
import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { Pill, statusTone } from "@/components/Pill";
import { Prose } from "@/components/Blocks";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { SectionRail } from "@/components/SectionRail";
import { loadLive, RefusalError, type Source } from "@/lib/api";
import { load, type Loaded } from "@/lib/artifacts";
import { count, shortAddress, timestamp } from "@/lib/format";

interface Skill {
  id: string;
  name: string;
  description: string;
}

interface AuditRow {
  ts: string;
  op: string;
  actor: string;
  chain_id: number;
  status: string;
  agent_id: number | null;
}

interface Command {
  name: string;
  summary: string;
}

interface NotDone {
  name: string;
  what: string;
  why: string;
  evidence: string;
}

export interface StudioArtifact {
  build: { command: string; generated_at: string; git_sha: string; git_dirty: boolean; source: string };
  agent: {
    url: string | null;
    name: string | null;
    description: string | null;
    protocol_version: string | null;
    preferred_transport: string | null;
    host: string | null;
    health_check: string | null;
    skills: Skill[];
    not_bag_deploy: string | null;
  };
  identity: {
    agent_id: number | null;
    chain_id: number | null;
    owner: string | null;
    endpoint: string | null;
    registered_by: string | null;
    verified: string | null;
    explorer: string;
    owner_url: string | null;
    audit: AuditRow[];
  };
  cli: {
    package: string | null;
    version: string | null;
    published: boolean | null;
    versions: number | null;
    read_at: string | null;
    install_page_reachable: boolean | null;
    commands: Command[];
    record: string;
  };
  commerce: {
    available: boolean;
    reason?: string;
    protocols?: string[];
    runtime?: string;
    network?: string;
    wallet_kind?: string;
    signer?: string;
    price_wei?: string;
    min_price_wei?: string;
    max_price_wei?: string;
    currency?: string;
    quote_ttl_seconds?: number;
    auto_settle?: boolean;
    note?: string;
  };
  negotiation: {
    available: boolean;
    reason?: string;
    read_at?: string;
    answered?: boolean;
    verdict?: string;
    checks?: CheckRow[];
    task_description?: string;
    negotiation_hash?: string;
    provider_sig?: string;
    chain_id?: number;
    verifying_contract?: string;
    price_wei?: string;
    currency?: string;
    evaluator_type?: string;
    quote_expires_at?: number;
    estimated_completion_seconds?: number;
    recovered_signer?: string;
    signed_over?: string;
    not_covered?: string;
    record?: string;
  };
  doctor: { pass: number | null; warn: number | null; fail: number | null };
  not_done: NotDone[];
}

/** What `/studio/negotiate` returns. The envelope, plus who signed it. */
interface LiveQuote {
  envelope: {
    negotiation_hash: string;
    provider_sig: string;
    chain_id: number;
    verifying_contract: string;
    response?: {
      quote_expires_at?: number;
      estimated_completion_seconds?: number;
      terms?: { price?: string; currency?: string; evaluator_type?: string };
    };
  };
  recovered_signer: string | null;
  signed_over: string;
  binds_to_the_verified_kernel: boolean;
  denominated_in_the_kernels_token: boolean;
  chain_matches: boolean;
  not_covered: string;
}

/**
 * Wei as a decimal, without a bignum library and without lying about precision.
 *
 * The payment token has eighteen decimals — `chain/addresses.py` refuses to
 * assume that anywhere and `EscrowConsole` reads `decimals()` rather than
 * guessing — but this figure comes out of `studio.toml`, where the unit is
 * declared beside the value in the same file the agent reads. It is
 * configuration quoted back, not a chain read, so the divisor is not a guess.
 *
 * String arithmetic rather than `Number`: 1e17 survives a double fine, and the
 * habit of putting token amounts through one does not.
 */
function fromWei(wei: string | undefined, decimals = 18): string | null {
  if (!wei || !/^\d+$/.test(wei)) return null;
  const padded = wei.padStart(decimals + 1, "0");
  const whole = padded.slice(0, padded.length - decimals);
  const frac = padded.slice(padded.length - decimals).replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole;
}

/** A hash or a signature, short enough to sit in a row and still be recognisable. */
function shortHex(value: string | undefined, lead = 10, tail = 8): string {
  if (!value || value.length <= lead + tail + 1) return value ?? "—";
  return `${value.slice(0, lead)}…${value.slice(-tail)}`;
}

/**
 * One field of the signed envelope.
 *
 * Mono and selectable, because the point of showing a signature is that
 * somebody copies it out and recovers the signer themselves. `break-all` for
 * the reason `OurAgents` documents: a 132-character signature is wider than a
 * 390px viewport on its own, and wrapping the row does not help when one token
 * exceeds the card.
 */
function Field({ label, value, title }: { label: string; value: React.ReactNode; title?: string }) {
  return (
    <div className="min-w-0">
      <dt className="font-mono text-[11px] tracking-wide text-faint uppercase">{label}</dt>
      <dd className="m-0 font-mono text-xs break-all text-ink" title={title}>
        {value}
      </dd>
    </div>
  );
}

/**
 * The envelope, from whichever source produced it.
 *
 * One renderer for the live answer and the recorded one, deliberately: two
 * would drift, and the whole claim of the recorded fallback is that it is the
 * same thing read at a different time. `AnsweredBy` carries the difference.
 */
function Envelope({
  hash,
  signature,
  signer,
  chainId,
  verifyingContract,
  priceWei,
  currency,
  bindsToKernel,
  source,
}: {
  hash?: string;
  signature?: string;
  signer?: string | null;
  chainId?: number;
  verifyingContract?: string;
  priceWei?: string;
  currency?: string;
  bindsToKernel: boolean;
  source: Source;
}) {
  const price = fromWei(priceWei);

  return (
    <div className="mt-4 rounded-md border border-glass-line bg-glass p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Heading className="m-0 font-mono text-xs tracking-wide text-faint uppercase">
          The signed envelope
        </Heading>
        <AnsweredBy source={source} />
      </div>

      <dl className="m-0 grid gap-3 sm:grid-cols-2">
        <Field label="negotiation hash" value={shortHex(hash)} title={hash} />
        <Field label="provider_sig" value={shortHex(signature)} title={signature} />
        {/* The one row that is not a quotation. Every other field here is the
            agent's word; this is what its signature recovers to, computed by
            `api/studio.py` against the same rule `scripts/studio_negotiate.py`
            uses. It is placed inside the envelope rather than beside it because
            a reader should not have to hold two blocks in their head to see
            that the signer and the identity owner are one address. */}
        <Field label="recovers to" value={signer ? shortAddress(signer) : "—"} title={signer ?? undefined} />
        <Field
          label="verifying contract"
          value={
            <span className="inline-flex flex-wrap items-baseline gap-2">
              <span title={verifyingContract}>{shortAddress(verifyingContract ?? "")}</span>
              {bindsToKernel && <Pill tone="pass">our kernel</Pill>}
            </span>
          }
        />
        <Field label="chain" value={chainId ?? "—"} />
        <Field
          label="price"
          value={
            price ? (
              <span title={currency}>
                {price} <span className="text-faint">{shortAddress(currency ?? "")}</span>
              </span>
            ) : (
              "—"
            )
          }
        />
      </dl>
    </div>
  );
}

export function StudioView({ initial }: { initial?: StudioArtifact }) {
  const [state, setState] = useState<Loaded<StudioArtifact> | null>(
    initial ? { ok: true, value: initial } : null,
  );

  // Same rule as every other route: the build's copy is a floor, and the
  // client's own load is the answer. A static export can be served long after
  // the artifact it was built from moved on.
  useEffect(() => {
    let live = true;
    load<StudioArtifact>("studio.json").then((next) => {
      if (live) setState(next);
    });
    return () => {
      live = false;
    };
  }, []);

  const [quote, setQuote] = useState<
    | { phase: "idle" }
    | { phase: "asking" }
    | { phase: "done"; value: LiveQuote; source: Source }
    | { phase: "refused"; error: RefusalError }
    | { phase: "unavailable" }
  >({ phase: "idle" });

  const ask = useCallback(async () => {
    setQuote({ phase: "asking" });
    // No artifact fallback inside the request, and that is deliberate — it is
    // the rule `RegistrySearch` states. The recorded envelope is already on the
    // page below; swapping it in as though the agent had just answered would be
    // a stale yes in place of a considered no.
    const got = await loadLive<LiveQuote>("/studio/negotiate");
    if (got.ok) return setQuote({ phase: "done", value: got.value, source: got.source });
    if (got.error instanceof RefusalError) return setQuote({ phase: "refused", error: got.error });
    setQuote({ phase: "unavailable" });
  }, []);

  const d = state?.ok ? state.value : undefined;
  const recorded = d?.negotiation;
  const live = quote.phase === "done" ? quote.value : null;

  return (
    <Loadable loading={state === null} what="the Agent Studio record">
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        A second agent, and it signs for itself
      </h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Scaffolded by the BNB Agent Studio CLI, deployed, carrying an ERC-8004
        identity that same CLI minted &mdash; and quoting ERC-8183 work under a
        signature you can check without this site&rsquo;s cooperation.
      </p>

      {state && !state.ok && (
        <div className="mt-10">
          <ErrorNotice
            title="The Agent Studio record has not been generated"
            detail={state.error.message}
            remedy={
              <>
                Run <code className="font-mono text-xs">make studio</code>. It needs no
                network &mdash;{" "}
                <code className="font-mono text-xs">make studio-negotiate</code> is the
                one that calls the agent.
              </>
            }
          />
        </div>
      )}

      {d && (
        <>
          <SectionRail
            label="On this page"
            items={[
              { id: "negotiate", label: "Ask it for a quote" },
              { id: "agent", label: "The agent" },
              { id: "identity", label: "Identity" },
              { id: "cli", label: "The CLI" },
              { id: "not-done", label: "What is missing" },
            ]}
          />

          {/* ------------------------------------------------- negotiate -- */}
          <Section
            id="negotiate"
            title="Ask it for a quote"
            className="mt-10"
            headingClassName="mb-2 text-lg font-semibold"
            intro={
              <>
                One request, no wallet and no money. The agent prices from a
                clamp in its own configuration &mdash; the model never prices
                &mdash; and signs the result with the key that owns its identity.
              </>
            }
          >
            <Card>
              {recorded?.task_description && (
                <p className="m-0 max-w-[68ch] text-sm text-dim">
                  It is asked:{" "}
                  <span className="text-ink">&ldquo;{recorded.task_description}&rdquo;</span>
                </p>
              )}

              <div className="mt-4 flex flex-wrap items-center gap-3">
                <Button onClick={() => void ask()} disabled={quote.phase === "asking"}>
                  {quote.phase === "asking" ? "Asking the agent…" : "Ask for a signed quote"}
                </Button>
                {d.agent.url && (
                  <a
                    href={`${d.agent.url}${d.agent.health_check ?? ""}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-sm"
                  >
                    Its agent card ↗
                  </a>
                )}
              </div>

              {/* The host sleeps. Said before the wait rather than after it. */}
              {quote.phase === "asking" && (
                <p className="mt-3 mb-0 text-xs text-faint" aria-live="polite">
                  The agent&rsquo;s host scales to zero, so a first request after an
                  idle hour pays a cold start of about a minute.
                </p>
              )}

              {quote.phase === "refused" && (
                <div className="mt-4">
                  <Refusal
                    title="The seller answered, and it was not a signed quote"
                    reason={quote.error.message}
                    floor={quote.error.remedy || undefined}
                  />
                </div>
              )}

              {quote.phase === "unavailable" && (
                <div className="mt-4">
                  <Refusal
                    title="The agent did not answer in time"
                    reason="Its host scales to zero, so the first request after an idle spell pays a cold start — and the request goes through this site's API, because the agent sends no cross-origin header and a browser cannot call it directly. Either can time out."
                    floor="Press it again. The envelope below was recorded earlier, and is the same call answered on a day the host was awake."
                  />
                </div>
              )}

              {live ? (
                <Envelope
                  hash={live.envelope.negotiation_hash}
                  signature={live.envelope.provider_sig}
                  signer={live.recovered_signer}
                  chainId={live.envelope.chain_id}
                  verifyingContract={live.envelope.verifying_contract}
                  priceWei={live.envelope.response?.terms?.price}
                  currency={live.envelope.response?.terms?.currency}
                  bindsToKernel={live.binds_to_the_verified_kernel}
                  source={quote.phase === "done" ? quote.source : "live"}
                />
              ) : recorded?.available ? (
                <Envelope
                  hash={recorded.negotiation_hash}
                  signature={recorded.provider_sig}
                  signer={recorded.recovered_signer}
                  chainId={recorded.chain_id}
                  verifyingContract={recorded.verifying_contract}
                  priceWei={recorded.price_wei}
                  currency={recorded.currency}
                  bindsToKernel
                  source="artifact"
                />
              ) : (
                <div className="mt-4">
                  <Refusal
                    title="Nothing has asked this agent for a quote"
                    reason={recorded?.reason ?? ""}
                    floor="make studio-negotiate"
                  />
                </div>
              )}

              {recorded?.signed_over && (
                <p className="mt-3 mb-0 text-xs text-faint">
                  Signed over {recorded.signed_over}. That encoding is documented
                  nowhere and recovering the other one returns a plausible wrong
                  address, so it is stated rather than left to be discovered.
                </p>
              )}
            </Card>

            {/* Why the envelope is worth anything, as checks rather than as a
                paragraph. Each row names the constant it was compared against
                and the file that constant lives in — the same
                `{name, status, detail, provenance}` shape `/vetting` and
                `/registry` already render, because it is the same question
                asked about a different subject. */}
            {recorded?.checks && recorded.checks.length > 0 && (
              <div className="mt-5">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <Heading className="m-0 text-md font-semibold">
                    What the signature is checked against
                  </Heading>
                  {recorded.verdict && (
                    <Pill tone={statusTone(recorded.verdict)}>{recorded.verdict}</Pill>
                  )}
                </div>
                <p className="mt-0 mb-3 max-w-[68ch] text-sm text-dim">
                  Three of these compare the agent&rsquo;s envelope against
                  addresses this repository recovered from{" "}
                  <Link href="/registry/#escrow">deployed bytecode</Link>, before
                  the scaffold existed. Two paths that never consulted each other
                  arriving at the same values is the corroboration; either alone
                  is a claim.
                </p>
                <CheckList checks={recorded.checks} />
                {recorded.not_covered && (
                  <div className="mt-3 text-xs text-faint">
                    <Prose text={recorded.not_covered} />
                  </div>
                )}
              </div>
            )}
          </Section>

          {/* ----------------------------------------------------- agent -- */}
          <Section
            id="agent"
            title="The agent itself"
            className="mt-12"
            headingClassName="mb-2 text-lg font-semibold"
          >
            <Card>
              <CardHeader
                title={d.agent.name ?? "the seller agent"}
                eyebrow={
                  <span className="font-mono normal-case">
                    A2A {d.agent.protocol_version} · {d.agent.preferred_transport} ·{" "}
                    {d.agent.host}
                  </span>
                }
                aside={
                  d.doctor.fail === 0 && d.doctor.pass != null ? (
                    <Pill tone="pass">
                      doctor {count(d.doctor.pass)} pass, {count(d.doctor.warn)} warn
                    </Pill>
                  ) : undefined
                }
              />
              {d.agent.description && (
                <p className="m-0 text-sm text-dim">{d.agent.description}</p>
              )}

              <div className="mt-4 grid gap-3">
                {d.agent.skills.map((skill) => (
                  <div
                    key={skill.id}
                    className="min-w-0 rounded-md border border-glass-line bg-glass p-3"
                  >
                    <div className="flex flex-wrap items-baseline gap-2">
                      <strong className="text-ink">{skill.name}</strong>
                      <code className="font-mono text-xs text-faint">{skill.id}</code>
                    </div>
                    <p className="mt-1 mb-0 text-xs text-dim">{skill.description}</p>
                  </div>
                ))}
              </div>

              {/* The distinction the whole page turns on, in the vendor's own
                  framing and kept verbatim from the record. Placed on the card
                  describing the deployment rather than in the not-done list at
                  the bottom, because a reader looking at "host: Render" should
                  be told immediately what that does and does not prove. */}
              {d.agent.not_bag_deploy && (
                <div className="mt-4 border-t border-line pt-3 text-xs text-faint">
                  <Prose text={d.agent.not_bag_deploy} />
                </div>
              )}
            </Card>

            {d.commerce.available && (
              <Card className="mt-4">
                <CardHeader
                  title="What it will charge, and who decided"
                  eyebrow={
                    <span className="font-mono normal-case">
                      studio.toml · {d.commerce.network} · {d.commerce.runtime}
                    </span>
                  }
                />
                <dl className="m-0 grid gap-3 sm:grid-cols-3">
                  <Field label="price" value={fromWei(d.commerce.price_wei) ?? "—"} />
                  <Field
                    label="clamped to"
                    value={`${fromWei(d.commerce.min_price_wei) ?? "—"} – ${fromWei(d.commerce.max_price_wei) ?? "—"}`}
                  />
                  <Field
                    label="quote valid"
                    value={
                      d.commerce.quote_ttl_seconds != null
                        ? `${count(d.commerce.quote_ttl_seconds)}s`
                        : "—"
                    }
                  />
                </dl>
                {d.commerce.note && (
                  <p className="mt-3 mb-0 text-xs text-faint">{d.commerce.note}</p>
                )}
                {d.commerce.protocols && (
                  <p className="mt-2 mb-0 text-xs text-faint">
                    Public faces: {d.commerce.protocols.join(", ")}. The signer is a{" "}
                    {d.commerce.wallet_kind} keystore the agent holds alone.
                  </p>
                )}
              </Card>
            )}
          </Section>

          {/* -------------------------------------------------- identity -- */}
          <Section
            id="identity"
            title="An identity the vendor's CLI minted"
            className="mt-12"
            headingClassName="mb-2 text-lg font-semibold"
            intro={
              <>
                Distinct from{" "}
                <Link href="/registry/#ours">the four we registered ourselves</Link>.
                Those were minted by <code className="font-mono text-xs">scripts/register_identity.py</code>;
                this one was not minted by anything in this repository.
              </>
            }
          >
            {d.identity.agent_id == null ? (
              <Refusal
                title="No Studio identity is recorded"
                reason="Nothing has run the Studio registration, so this is not a claim that none exists."
                floor="bag erc8004 register"
              />
            ) : (
              <Card>
                <CardHeader
                  title={`ERC-8004 #${d.identity.agent_id}`}
                  eyebrow={
                    <span className="font-mono normal-case">chain {d.identity.chain_id}</span>
                  }
                  aside={<Pill tone="pass">{d.identity.registered_by?.split("—")[0]?.trim()}</Pill>}
                />
                {d.identity.owner && (
                  <p className="m-0 text-sm text-dim">
                    Owned by{" "}
                    <a
                      className="font-mono text-xs"
                      href={d.identity.owner_url ?? undefined}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {shortAddress(d.identity.owner)}
                    </a>{" "}
                    &mdash; the wallet the envelope above recovers to.
                  </p>
                )}
                {d.identity.verified && (
                  <p className="mt-3 mb-0 text-sm text-dim">{d.identity.verified}</p>
                )}

                {/* The CLI's own log, which is the one part of this story not
                    written by us. Two rows: submitted, then confirmed with the
                    id in it. Rendered because "the vendor's tool did this"
                    is exactly the claim a judge would want a receipt for. */}
                {d.identity.audit.length > 0 && (
                  <div className="mt-4 border-t border-line pt-3">
                    <Heading className="mt-0 mb-2 font-mono text-[11px] tracking-wide text-faint uppercase">
                      From the CLI&rsquo;s own audit log
                    </Heading>
                    <ul className="m-0 list-none space-y-1 p-0 font-mono text-xs">
                      {d.identity.audit.map((row) => (
                        <li key={`${row.ts}-${row.status}`} className="flex flex-wrap gap-x-3 text-dim">
                          <span className="text-faint">{timestamp(row.ts)}</span>
                          <span className="text-ink">{row.op}</span>
                          <span>{row.actor}</span>
                          <span>chain {row.chain_id}</span>
                          <span>{row.status}</span>
                          {row.agent_id != null && <span className="text-ink">#{row.agent_id}</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Card>
            )}
          </Section>

          {/* ------------------------------------------------------- cli -- */}
          <Section
            id="cli"
            title="The CLI, and what it turned out to offer"
            className="mt-12"
            headingClassName="mb-2 text-lg font-semibold"
            intro={
              <>
                This work sat parked for a fortnight on &ldquo;the vendor cannot
                be reached&rdquo;. Half true &mdash; the install page does not
                resolve &mdash; and no reason at all that the package cannot be
                installed, which nobody had checked.
              </>
            }
          >
            <Card>
              <CardHeader
                title={d.cli.package ?? "the Studio CLI"}
                eyebrow={
                  <span className="font-mono normal-case">
                    {d.cli.version} · {count(d.cli.versions)} versions published ·
                    read {timestamp(d.cli.read_at)}
                  </span>
                }
                aside={
                  d.cli.install_page_reachable === false ? (
                    <Pill tone="unverified">install page down</Pill>
                  ) : undefined
                }
              />
              <ul className="m-0 list-none space-y-2 p-0">
                {d.cli.commands.map((command) => (
                  <li key={command.name} className="flex flex-wrap items-baseline gap-x-3">
                    <code className="font-mono text-xs text-ink">bag {command.name}</code>
                    <span className="min-w-0 text-sm text-dim">{command.summary}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-4 mb-0 border-t border-line pt-3 text-xs text-faint">
                The full dated probe, with status codes, is at{" "}
                <code className="font-mono text-xs">{d.cli.record}</code>.
              </p>
            </Card>
          </Section>

          {/* -------------------------------------------------- not done -- */}
          <Section
            id="not-done"
            title="What this does not prove"
            className="mt-12"
            headingClassName="mb-2 text-lg font-semibold"
            intro={
              <>
                The half a judge will check. Kept in the shape{" "}
                <Link href="/status">the ledger</Link> uses &mdash; what it would
                have been, why it is not, and a path to check that against.
              </>
            }
          >
            <div className="grid gap-4">
              {d.not_done.map((entry) => (
                <Card key={entry.name} className="hatched [--hatch-tone:var(--hatch-none)]">
                  <CardHeader title={entry.name} aside={<Pill tone="none">not done</Pill>} />
                  {/* `Prose`, not the raw string — the same call
                      `Ledger.tsx` makes about the same two fields. Both are
                      written with inline markdown because both name commands
                      and paths, and printing the backticks is how a reader
                      learns to distrust the rest of the page. */}
                  <div className="text-sm text-ink">
                    <Prose text={entry.what} />
                  </div>
                  <div className="mt-2 text-sm text-dim">
                    <Prose text={entry.why} />
                  </div>
                  <p className="mt-3 mb-0 font-mono text-xs text-faint">{entry.evidence}</p>
                </Card>
              ))}
            </div>
          </Section>

          <p className="mt-10 mb-0 text-sm text-dim">
            The escrow this agent quotes against is the same one{" "}
            <Link href="/registry/#escrow">
              a job was funded and reclaimed on, with real money on BSC mainnet
            </Link>
            .
          </p>
        </>
      )}
    </Loadable>
  );
}
