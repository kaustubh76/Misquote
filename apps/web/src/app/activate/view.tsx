"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { Heading, Section } from "@/components/Heading";
import { Pill } from "@/components/Pill";
import { Prose } from "@/components/Blocks";
import { HireEscrow, type HireableAgent } from "@/components/HireEscrow";
import type { EscrowDeployment } from "@/lib/escrow";
import { HireFlow } from "@/components/HireFlow";
import { AnsweredBy } from "@/components/AnsweredBy";
import { loadLive, type Source } from "@/lib/api";

interface Step {
  name: string;
  sender: string;
  what: string;
}

interface Capability {
  available: boolean;
  module: string | null;
  reason: string;
  evidence?: string[];
  grant_plan: Step[];
  revoke_plan: Step[];
  readable_without_a_signer: string[];
  not_readable_here?: string[];
  needs_a_signer: string[];
}

interface ProofTx {
  call: string;
  tx: string;
  explorer: string;
}

export interface SessionKeySurvey {
  verdict?: string;
  block?: number | null;
  checks?: { name: string; status: string; detail: string }[];
  not_verified?: string[];
}

export interface SessionProof {
  transactions?: ProofTx[];
  valid_after_grant?: boolean;
  valid_after_revoke?: boolean;
  key_store?: string;
  owner?: string;
  caps_enforced?: boolean;
}

/**
 * The activation surface, and the half of it that is now proven on chain.
 *
 * This page was built before there was anything to activate against, and said
 * so: no Altana session-key module had been verified, so a grant had nowhere to
 * go. That reason was a statement about `vetting/addresses/` rather than about
 * the chain — the SDK published the addresses the whole time, in the same
 * package `JOB_ESCROW` was verified from. P-27.
 *
 * So the page now carries a round trip instead of a plan for one: a key granted
 * on chapel, read back live, revoked, and read back dead, with three
 * transaction hashes anyone can check without this site's cooperation.
 *
 * **There is a Hire button now, and the disclosure moved next to it.** For a
 * long time this page refused instead: the keystore enforces the expiry and
 * revocation but not the allowlist or the spend cap — those belong to a
 * `validator` module nothing here has read, and every grant on this deployment,
 * ours and other people's, carries `validator = 0x0` — so a button offering
 * four caps over a key the chain bounds by one would have been the misquote
 * this project is named after, on the page whose subject is bounded authority.
 *
 * Every one of those facts is still true. What changed is the conclusion drawn
 * from them. A marketplace that answers "can I hire an agent" with a paragraph
 * is not being careful; the careful version grants the one cap the chain
 * honours and names the two it does not, at the moment of signing, which is
 * where a caveat can still change a decision. `HireFlow` carries it inline.
 *
 * `scripts/check-pages.mjs` now matches "not the allowlist or the spend cap" in the
 * no-JS render of this route. The needle followed the honesty rather than the
 * button, because the honesty is what it was protecting.
 *
 * Standing prose is prerendered; only the live capability read needs
 * JavaScript, and its absence renders the same answer from the fallbacks.
 */
/** `hire_flow`, narrowed to what escrowing a budget from a browser needs. */
export interface EscrowHalf {
  deployments?: Record<string, EscrowDeployment>;
  errors?: Record<string, string>;
  mainnet_proof?: { budget?: number };
}

export function ActivateView({
  proof,
  survey,
  escrow,
  agents,
  owner,
}: {
  proof?: SessionProof;
  survey?: SessionKeySurvey;
  escrow?: EscrowHalf;
  /** The four agents this marketplace lists, for the "who delivers" choice. */
  agents?: HireableAgent[];
  /** The wallet holding their ERC-8004 identities — the default provider. */
  owner?: string;
}) {
  const [cap, setCap] = useState<Capability | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      const got = await loadLive<Capability>("/sessions/capability");
      if (!live) return;
      if (got.ok) {
        setCap(got.value);
        setSource(got.source);
      }
      setChecked(true);
    })();
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        Hire an agent. Bounded, reversible, yours to revoke.
      </h1>
      <p className="mt-4 max-w-[62ch] text-md text-dim">
        A session key your wallet grants and can take back. The contract enforces
        the expiry and the revoke — not the allowlist or the spend cap, and the
        button says so before you sign.
      </p>

      {/* This page used to render a large refusal here, headed "There is no Hire
          button on this site", and `scripts/check-pages.mjs` matched that
          sentence in the no-JS pass.

          The facts behind it were right and are unchanged — every grant on this
          deployment carries `validator 0x0`, so the allowlist and the spend cap
          are not enforced by anything. What was wrong was the conclusion. A
          marketplace whose answer to "can I hire an agent" is a paragraph is not
          being careful, it is being unusable; and the honest form of the same
          argument is a button that grants the one cap the chain honours and
          names the two it does not, at the moment of signing.

          `HireFlow` carries that warning inline. The needle in `check-pages.mjs`
          moved with it. */}
      {/* Two halves, in the order they happen. Escrowing a budget is the
          hire; a session key is what lets the agent act once hired. The escrow
          was the half with no way in — built, mined on mainnet, and reachable
          only by scrolling six screens down a different page. */}
      <div className="-mx-5 mt-8 px-5">
        <HireEscrow
          deployments={escrow?.deployments}
          defaultBudget={escrow?.mainnet_proof?.budget}
          errors={escrow?.errors}
          agents={agents}
          owner={owner}
        />
      </div>

      <div className="-mx-5 mt-6 px-5">
        <HireFlow />
      </div>

      {/* Was "What a grant would consist of", in the conditional, on a page
          that could not perform one. The button above performs it now, so this
          says what you are signing rather than what signing would be like.

          Three paragraphs of development history came out with the retitle —
          which transaction was wrongly called an ERC-20 approve, what the
          bootstrap revert said, which claim survived contact with the ABI. All
          of it is true and none of it belongs between a reader and a button:
          it is an account of how this page was corrected, not of what happens
          when you press the thing. The corrections live in the git history and
          in `/assumptions`, where a reader who wants them is looking for them. */}
      <Section
        title="What you are signing"
        className="mt-10"
        headingClassName="text-lg font-semibold"
      >
        <p className="mt-2 mb-5 max-w-[62ch] text-dim">
          Both transactions are sent by you. No key of yours leaves your wallet,
          and the second one is a bootstrap the contract requires only of a
          wallet that has never registered a key.
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader
              title="Granting"
              eyebrow="two transactions, once per wallet"
              aside={<Pill tone="pass">Proven on chapel</Pill>}
            />
            <StepList steps={cap?.grant_plan ?? FALLBACK_GRANT} />
            <p className="mt-3 mb-0 text-xs text-faint">
              A wallet that has already bootstrapped sends one, not two — and
              whether it has is read, not assumed.
            </p>
          </Card>

          <Card>
            <CardHeader
              title="Revoking"
              eyebrow="one transaction"
              aside={<Pill tone="pass">Proven on chapel</Pill>}
            />
            <StepList steps={cap?.revoke_plan ?? FALLBACK_REVOKE} />
            <p className="mt-3 mb-0 text-xs text-faint">
              Sent by you, needing no cooperation from the agent.
            </p>
          </Card>
        </div>

        {/* The one claim the removed path dump made that a reader can act on. */}
        <p className="mt-5 mb-0 max-w-[62ch] text-sm text-dim">
          Every address here passed the same three-way check{" "}
          <Link href="/registry">the hire flow</Link> uses — never a vendor&rsquo;s word for it.
        </p>
      </Section>

      {proof?.transactions?.length ? (
        <Section
          title="The round trip, on chain"
          className="mt-10"
          headingClassName="text-lg font-semibold"
        >
          <p className="mt-2 mb-5 max-w-[62ch] text-dim">
            Every other page is a <em>reading</em> you have to trust. These are
            transaction hashes you can check without this page&rsquo;s cooperation.
          </p>

          <ol className="m-0 list-none space-y-3 p-0">
            {proof.transactions.map((tx, index) => (
              <li key={tx.tx} className="flex gap-3">
                <span className="tabular mt-0.5 shrink-0 rounded-full bg-brand-bg px-2 py-0.5 font-mono text-xs text-brand">
                  {index + 1}
                </span>
                <span className="min-w-0">
                  <span className="font-mono text-sm text-ink">{tx.call}</span>
                  <a
                    className="block truncate font-mono text-xs text-dim underline"
                    href={tx.explorer}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {tx.tx}
                  </a>
                </span>
              </li>
            ))}
          </ol>

          <div className="mt-5 flex flex-wrap gap-3 text-sm">
            <Pill tone={proof.valid_after_grant ? "pass" : "fail"}>
              isValidKey after grant: {String(proof.valid_after_grant)}
            </Pill>
            <Pill tone={proof.valid_after_revoke === false ? "pass" : "fail"}>
              isValidKey after revoke: {String(proof.valid_after_revoke)}
            </Pill>
            <Pill tone="fail">caps enforced: {String(proof.caps_enforced ?? false)}</Pill>
          </div>

          <p className="mt-4 mb-0 max-w-[62ch] text-sm text-dim">
            The third pill is the honest one: the key was bounded and withdrawn,
            but the caps were never enforced, so they are reported absent rather
            than folded into a green tick.
          </p>
        </Section>
      ) : null}

      {survey?.not_verified?.length ? (
        <Section
          title="What the verification does not establish"
          className="mt-10"
          headingClassName="text-lg font-semibold"
        >
          <p className="mt-2 mb-4 max-w-[62ch] text-dim">
            {survey.checks?.length ?? 0} checks passed against the deployment
            {typeof survey.block === "number"
              ? `, read at block ${survey.block.toLocaleString()}`
              : ""}
            . A passing check says what was read, never what the reading covers.
          </p>
          <ul className="m-0 list-none space-y-3 p-0 text-sm text-dim">
            {survey.not_verified.map((line) => (
              <li key={line} className="border-glass-line border-l-2 pl-3">
                <Prose text={line} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Heading className="mt-10 mb-2 text-md font-semibold">
        What is readable, what is not, and what needs your signature
      </Heading>
      <div className="grid gap-6 sm:grid-cols-3">
        <Column
          title="Readable without a signer"
          items={cap?.readable_without_a_signer ?? FALLBACK_READABLE}
        />
        <Column
          title="Not readable here"
          items={cap?.not_readable_here ?? FALLBACK_NOT_READABLE}
        />
        <Column title="Needs a signature" items={cap?.needs_a_signer ?? ["grant", "revoke"]} />
      </div>
      <p className="mt-3 mb-0 max-w-[62ch] text-sm text-faint">
        {/* Was an account of how these three columns came to be split — four
            things once listed as readable that no code read. True, and about
            this page's history rather than about the reader's key. What
            survives is the fact that changes what they should expect. */}
        Two of these caps are enforced somewhere nobody here has looked, which
        is why they are listed apart from the ones this site can read.
      </p>

      {/* This said "Read live from the activation endpoint" in prose — the same
          claim `AnsweredBy` makes, hand-rolled here because the component did
          not exist, and derived from `cap != null` rather than from the
          `source` `loadLive` had already returned. Two ways of saying one thing,
          and the prose one could not tell a live answer from a fallback. */}
      <p className="mt-8 mb-0 text-sm text-faint" role={checked ? undefined : "status"}>
        {checked && source ? (
          <AnsweredBy source={source} className="mr-2 align-baseline" />
        ) : (
          <>Standing description. The live endpoint says the same thing. </>
        )}
        <Link href="/status">Readiness</Link> lists everything else that is and is
        not built.
      </p>
    </>
  );
}

function StepList({ steps }: { steps: Step[] }) {
  return (
    <ol className="m-0 list-none space-y-3 p-0">
      {steps.map((step, index) => (
        <li key={step.name} className="flex gap-3">
          <span className="tabular mt-0.5 shrink-0 rounded-full bg-brand-bg px-2 py-0.5 font-mono text-xs text-brand">
            {index + 1}
          </span>
          <span className="min-w-0">
            <span className="font-mono text-sm text-ink">{step.name}</span>
            <span className="block text-sm text-dim">{step.what}</span>
            <span className="block text-xs text-faint">sent by the {step.sender}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function Column({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <Heading className="m-0 mb-2 text-sm font-semibold text-ink">{title}</Heading>
      <ul className="m-0 list-none space-y-1 p-0 text-sm text-dim">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The standing answer, for a reader with no JavaScript or no API.
 *
 * Not a placeholder: it is the same content `sessions/keys.py` serves, and
 * `tests/api/test_sessions_routes.py` pins the shape it mirrors. A page whose
 * prerendered state said "loading" would be telling a reader without JavaScript
 * that activation is unknown, when it is known and the answer is no.
 */
const FALLBACK_GRANT: Step[] = [
  {
    name: "initialRegisterKey",
    sender: "owner",
    what:
      "bootstrap the account with a root key, on the keyStoreController. Payable, and its expiry must be zero — the contract refuses a root key that expires",
  },
  {
    name: "registerKey",
    sender: "owner",
    what:
      "register the session key with its expiry, on the keyStoreController; payable, and the fee is read at send time because it moves",
  },
];

const FALLBACK_REVOKE: Step[] = [
  {
    name: "revokeKey",
    sender: "owner",
    what:
      "revoke the session key, on the keyStore — a different contract from the grant; the agent's next transaction reverts",
  },
];

const FALLBACK_READABLE = [
  "which key ids a wallet has registered (keyStore.getKeys)",
  "whether a key is still live, i.e. not revoked (keyStore.isValidKey)",
  "the key itself (keyStore.getPublicKey)",
  "what a grant costs right now (keyStoreController.getRegistrationFeeInWei)",
];

const FALLBACK_NOT_READABLE = [
  "the allowlist a key was granted — it is the validator module's, and this repository has not read that module",
  "its spend cap and how much is left — same place, same absence",
];
