"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { Heading, Section } from "@/components/Heading";
import { Pill } from "@/components/Pill";
import { Prose } from "@/components/Blocks";
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
  searched: string[];
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
 * `scripts/check-pages.mjs` now matches "does not enforce the allowlist" in the
 * no-JS render of this route. The needle followed the honesty rather than the
 * button, because the honesty is what it was protecting.
 *
 * Standing prose is prerendered; only the live capability read needs
 * JavaScript, and its absence renders the same answer from the fallbacks.
 */
export function ActivateView({
  proof,
  survey,
}: {
  proof?: SessionProof;
  survey?: SessionKeySurvey;
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
        A session key your wallet grants and your wallet can take back. The
        contract enforces the expiry and the revoke; it does not enforce the
        allowlist or the spend cap, and the button below says so before you sign
        rather than after.
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
      <div className="-mx-5 mt-8 px-5">
        <HireFlow />
      </div>

      <Section
        title="What a grant would consist of"
        className="mt-10"
        headingClassName="text-lg font-semibold"
      >
        <p className="mt-2 mb-5 max-w-[62ch] text-dim">
          Read off the verified deployment, not off the standard. The count was
          right before anyone checked and every reason given for it was wrong:
          there is no token approval, and the second transaction is a bootstrap
          the contract requires of a wallet that has never registered a key. Both
          are sent by you; neither is sent by us, and no key of yours leaves your
          wallet.
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
              This page used to say the first transaction was an ERC-20 approve.
              It is not — running it returned{" "}
              <span className="font-mono">KeyStore: account not bootstrapped</span>,
              and the root key that clears it{" "}
              <span className="font-mono">must not expire</span>. A wallet that has
              already bootstrapped sends one transaction, and whether it has is
              read rather than assumed.
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
              One, sent by you, with no cooperation from the agent required — the
              one claim on this page that survived contact with the ABI unchanged.
              What reading it added is <em>where</em>: the revoke goes to the
              keyStore and the grant to the keyStoreController, two different
              contracts.
            </p>
          </Card>
        </div>
      </Section>

      {proof?.transactions?.length ? (
        <Section
          title="The round trip, on chain"
          className="mt-10"
          headingClassName="text-lg font-semibold"
        >
          <p className="mt-2 mb-5 max-w-[62ch] text-dim">
            Everything else on this site is a <em>reading</em> of chain state,
            which has to be trusted to have been taken honestly. These are
            transaction hashes — a third-party-hosted record of an action, which
            you can check without this page&rsquo;s cooperation. Grant, read back
            live, revoke, read back dead.
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
            The third pill is the one that keeps this page honest. The key really
            was bounded and really was withdrawn; what the chain never enforced
            was the allowlist or the spend cap, so they are reported as absent
            rather than folded into a green tick with the two that worked.
          </p>
        </Section>
      ) : null}

      <Section
        title="What was searched"
        className="mt-10"
        headingClassName="text-lg font-semibold"
      >
        <p className="mt-2 mb-3 max-w-[62ch] text-dim">
          A refusal that does not say where it looked is not checkable — and this
          list is the whole reason the refusal lasted as long as it did. It used
          to name three files, all of them this repository&rsquo;s own output, and
          conclude from their contents that no session-key module had been
          verified anywhere. The addresses were in a package we had already read a
          different table out of.
        </p>
        <ul className="m-0 list-none space-y-1 p-0 font-mono text-sm text-dim">
          {(cap?.searched ?? FALLBACK_SEARCHED).map((where) => (
            <li key={where}>{where}</li>
          ))}
        </ul>
        <p className="mt-4 mb-0 max-w-[62ch] text-sm text-dim">
          The bar did not move: an address earns a place in the code by passing
          the same three-way check <Link href="/registry">the hire flow</Link>{" "}
          uses — it is a contract, it answers the calls we make, and it was
          observed on a live network — and not by appearing in a vendor&rsquo;s
          SDK. What changed is that somebody finally ran it.
        </p>
      </Section>

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
            . This is the other half of the record, and the half worth more: a
            passing check says what was read, never what the reading covers. The
            escrow that cleared four real checks and implemented none of ERC-8183
            is why this section exists.
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
        The middle column used to be part of the first one. Four things were
        listed as readable and no code read any of them; reading the deployment
        did not turn four promises into four reads, it showed that two of them are
        enforced somewhere nobody here has looked.
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

const FALLBACK_SEARCHED = [
  "@altananetwork/sdk@0.8.0 dist/config.js",
  "@altananetwork/sdk@0.8.0 dist/internal/keystore.js",
  "vetting/addresses/session-keys-56.json",
  "vetting/addresses/session-keys-97.json",
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
