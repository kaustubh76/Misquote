"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { Heading, Section } from "@/components/Heading";
import { Pill } from "@/components/Pill";
import { Refusal } from "@/components/Refusal";
import { loadLive } from "@/lib/api";

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
  grant_plan: Step[];
  revoke_plan: Step[];
  readable_without_a_signer: string[];
  needs_a_signer: string[];
}

/**
 * The activation surface, built before there is anything to activate against.
 *
 * `Readme.md` §1 puts the caps subset on the never-cut list, and it has been a
 * docstring for the life of the project. What blocks it is not the code: it is
 * that no Altana session-key module has been verified on either network, so
 * there is no address to send a grant to. `sessions/keys.py::SESSION_KEY_MODULE`
 * is empty and `tests/web/test_ledger.py` reads that symbol to check the
 * published claim, which means the day someone records a real address this page
 * and the ledger both have to change or the suite goes red.
 *
 * The page is worth having anyway, because the *plan* is a fact about the caps
 * subset rather than about a deployment. "Revoking is one transaction, sent by
 * you" is the product's central activation claim, and it can be shown — and
 * checked — before an address exists. What must never appear here is a Hire
 * button, which is the whole reason the ledger entry says what it says.
 *
 * Standing prose is prerendered; only the live capability read needs
 * JavaScript, and its absence renders as the same refusal the API returns.
 */
export function ActivateView() {
  const [cap, setCap] = useState<Capability | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      const got = await loadLive<Capability>("/sessions/capability");
      if (!live) return;
      if (got.ok) setCap(got.value);
      setChecked(true);
    })();
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        Hiring an agent should be bounded and reversible.
      </h1>
      <p className="mt-4 max-w-[62ch] text-md text-dim">
        An allowlist of what it may call, a cap on what it may spend, an expiry, and
        a revoke you can send yourself. That is the whole of what activation is
        here — and it is not built, because there is no verified contract to send
        it to.
      </p>

      {/* Bled to the container edge and one type step up, because on this page
          the refusal is not an aside to the argument — it is the argument. The
          wording is untouched: `scripts/check-pages.mjs` matches "no Hire
          button" in the no-JS render of this route, and it is the sentence the
          page exists to make either way. */}
      <div className="-mx-5 mt-8 px-5">
        <Refusal
          size="lg"
          title="There is no Hire button on this site"
          reason={
            cap?.reason ??
            "No Altana session-key module has been verified on either network, so a grant would have nowhere to go."
          }
          floor="A button that did nothing would be worse than an absent one."
        />
      </div>

      <Section
        title="What a grant would consist of"
        className="mt-10"
        headingClassName="text-lg font-semibold"
      >
        <p className="mt-2 mb-5 max-w-[62ch] text-dim">
          These are facts about the caps subset, not about any deployment — the
          count does not change when an address is finally recorded. Both
          transactions are sent by you; neither is sent by us, and no key of yours
          leaves your wallet.
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader
              title="Granting"
              eyebrow="two transactions"
              aside={<Pill tone="none">Not available</Pill>}
            />
            <StepList steps={cap?.grant_plan ?? FALLBACK_GRANT} />
            <p className="mt-3 mb-0 text-xs text-faint">
              The approve is the one that gets forgotten. A session key that may
              spend a token needs that token approved to the module first, so a
              demo showing only the grant looks like a one-transaction flow until
              it is run.
            </p>
          </Card>

          <Card>
            <CardHeader
              title="Revoking"
              eyebrow="one transaction"
              aside={<Pill tone="none">Not available</Pill>}
            />
            <StepList steps={cap?.revoke_plan ?? FALLBACK_REVOKE} />
            <p className="mt-3 mb-0 text-xs text-faint">
              One, sent by you, with no cooperation from the agent required. That
              is the claim the caps subset is for.
            </p>
          </Card>
        </div>
      </Section>

      <Section
        title="What was searched"
        className="mt-10"
        headingClassName="text-lg font-semibold"
      >
        <p className="mt-2 mb-3 max-w-[62ch] text-dim">
          A refusal that does not say where it looked is not checkable. These are
          the address records this repository keeps, and none of them contains a
          session-key module.
        </p>
        <ul className="m-0 list-none space-y-1 p-0 font-mono text-sm text-dim">
          {(cap?.searched ?? FALLBACK_SEARCHED).map((where) => (
            <li key={where}>{where}</li>
          ))}
        </ul>
        <p className="mt-4 mb-0 max-w-[62ch] text-sm text-dim">
          The precedent for closing this is{" "}
          <Link href="/registry">the hire flow</Link>: an address earns a place in
          the code by passing the same three-way check — it is a contract, it
          answers the calls we make, and it was observed on a live network — and
          not by appearing in a vendor&rsquo;s SDK.
        </p>
      </Section>

      <Heading className="mt-10 mb-2 text-md font-semibold">
        What would be readable, and what needs your signature
      </Heading>
      <div className="grid gap-6 sm:grid-cols-2">
        <Column
          title="Readable without a signer"
          items={cap?.readable_without_a_signer ?? FALLBACK_READABLE}
        />
        <Column title="Needs a signature" items={cap?.needs_a_signer ?? ["grant", "revoke"]} />
      </div>

      <p className="mt-8 mb-0 text-sm text-faint" role={checked ? undefined : "status"}>
        {checked && cap
          ? "Read live from the activation endpoint."
          : "Standing description. The live endpoint says the same thing."}{" "}
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
    name: "approve",
    sender: "owner",
    what: "approve the spend cap's token to the session-key module",
  },
  {
    name: "grant",
    sender: "owner",
    what: "register the session key with its allowlist, cap and expiry",
  },
];

const FALLBACK_REVOKE: Step[] = [
  {
    name: "revoke",
    sender: "owner",
    what: "revoke the session key; the agent's next transaction reverts",
  },
];

const FALLBACK_SEARCHED = [
  "vetting/addresses/56.json",
  "vetting/addresses/erc8183-56.json",
  "vetting/addresses/erc8183-97.json",
];

const FALLBACK_READABLE = [
  "the allowlist a key was granted",
  "its spend cap and how much is left",
  "its expiry",
  "whether it has been revoked",
];
