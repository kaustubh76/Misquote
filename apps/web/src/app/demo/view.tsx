import Link from "next/link";
import { Card, CardHeader } from "@/components/Card";
import { Heading, Section } from "@/components/Heading";
import { Pill } from "@/components/Pill";
import type { ScenarioSummary } from "@/lib/build-artifact";

/**
 * The way in.
 *
 * `lib/scenario.ts` has been a complete, tested, deployed simulation layer for a
 * while — and **nothing anywhere linked to it**. The only affordance in the whole
 * UI was the button that *leaves* a simulation. To see the feature you had to
 * know `?scenario=` existed and then guess one of three names printed on no page,
 * in no README, in no judge document.
 *
 * That is this project's recurring defect wearing a new hat: built, correct, and
 * wired to no reader.
 *
 * ## Why this is a server component with no state
 *
 * The list is read off disk at build time by `readScenarios()` and rendered as
 * plain links. Nothing here fetches, nothing here is simulated — this page is a
 * *table of contents*, and it must stay honest when the API is asleep, which is
 * exactly when somebody is most likely to be reading it.
 *
 * It also means the list cannot drift: adding a fixture publishes it and deleting
 * one un-publishes it, the same discipline the not-built ledger uses.
 *
 * ## What it must not do
 *
 * Not start a simulation itself, and not persist one. `scenario.ts`'s fourth rule
 * is "never the default and never sticky", and a demo page that flipped a global
 * would be the thing that rule exists to prevent. Every step below is an ordinary
 * link to an ordinary page carrying a query parameter, and every one of them
 * arrives with the banner on.
 */
export function DemoView({ scenarios }: { scenarios: ScenarioSummary[] }) {
  const happy = scenarios.find((s) => s.name === "demo-quote");
  const rest = scenarios.filter((s) => s.name !== "demo-quote");

  return (
    <>
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        See it work, without a wallet.
      </h1>
      <p className="mt-4 max-w-[62ch] text-md text-dim">
        The states that need a running API, a worker, or a BSC position you do not
        hold — recorded, and replayed here from files you can read.
      </p>

      <div className="-mx-5 mt-8 px-5">
        <Card>
          <CardHeader title="What a simulation is here" eyebrow="four rules" />
          <ul className="m-0 mt-2 list-none space-y-2 p-0 text-sm text-dim">
            <li>
              <strong className="text-ink">It is a different code path, not a different answer.</strong>{" "}
              A scenario short-circuits above the API client, so under one{" "}
              <em>no request is issued at all</em>. Simulated data cannot arrive by
              the route live data arrives by.
            </li>
            <li>
              <strong className="text-ink">It can only ever be labelled simulated.</strong>{" "}
              There is no branch that returns a recorded answer as live. The label
              comes from where the answer came from, never from what came back.
            </li>
            <li>
              <strong className="text-ink">A refusal stays a refusal.</strong> Most of
              what is worth showing here is the engine declining to answer, and a
              demo that could only succeed is the thing every other marketplace
              already has.
            </li>
            <li>
              <strong className="text-ink">It is never on by default and never sticky.</strong>{" "}
              Read from the URL and nowhere else &mdash; so a reload of a clean link
              is a real page, and no simulated HTML exists in this site&rsquo;s
              export at all.
            </li>
          </ul>
        </Card>
      </div>

      {happy && (
        <Section
          title="The guided run"
          className="mt-10"
          headingClassName="text-lg font-semibold"
          intro={
            <>
              Four real pages with the simulation banner on them &mdash; not a mock,
              not a video. The last one is not simulated at all.
            </>
          }
        >
          <ol className="m-0 list-none space-y-4 p-0">
            <Step
              n={1}
              title="Pick something to have handled"
              href="/category/"
              note="Four categories, four agents, each card a mini-tearsheet built from a replay over real pool history."
            />
            <Step
              n={2}
              title="Ask for a quote on a wallet you do not own"
              href={`/quote/?scenario=${happy.name}`}
              note="A recorded wallet with one quotable position. Paste any address — the fixture answers for all of them, because a demo cannot know yours in advance."
              simulated
            />
            <Step
              n={3}
              title="Run the replay and read the range"
              href={`/quote/?scenario=${happy.name}`}
              note="Press “Replay this pool”. The answer is a P25–P75 range recorded from a real job on the real tape, with the assumption sheet one click away."
              simulated
            />
            <Step
              n={4}
              title="See what hiring involves, and what it did"
              href="/activate/"
              note="Not simulated. Three mined chapel transactions — bootstrap, grant, revoke — with isValidKey reading true and then false. Real receipts you can open on a block explorer."
            />
          </ol>
        </Section>
      )}

      <Section
        title="Every recorded state"
        className="mt-10"
        headingClassName="text-lg font-semibold"
        intro={
          <>
            Read from <code className="font-mono text-xs">public/scenarios/</code>{" "}
            when this page was built, so the list is whatever the site can actually
            serve.
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          {rest.map((scenario) => (
            <Card key={scenario.name}>
              <CardHeader
                title={scenario.label}
                eyebrow={<span className="font-mono normal-case">{scenario.name}</span>}
                aside={<Pill tone="unverified">Simulated</Pill>}
              />
              <p className="mt-2 mb-3 text-sm text-dim">{scenario.why}</p>
              <p className="m-0 text-xs text-faint">
                answers{" "}
                {scenario.paths.map((path, i) => (
                  <span key={path}>
                    {i > 0 && ", "}
                    <code className="font-mono">{path}</code>
                  </span>
                ))}
              </p>
              {scenario.route ? (
                <p className="mt-3 mb-0 text-sm">
                  <Link href={`${scenario.route}?scenario=${scenario.name}`}>
                    Open this state &rarr;
                  </Link>
                </p>
              ) : (
                <p className="mt-3 mb-0 text-xs text-faint">
                  No page carries this state yet.
                </p>
              )}
            </Card>
          ))}
        </div>
      </Section>

      <Heading className="mt-10 mb-2 text-md font-semibold">
        What is simulated, and what never is
      </Heading>
      <p className="max-w-[70ch] text-sm text-dim">
        Every number on the agent cards, the advantage report, the badges and the
        registry survey is computed from chain state — none of it is simulated.
        What is recorded above is the{" "}
        <em>live API&rsquo;s side of a conversation</em>: a quote job, a wallet
        read, a journal that does not exist.
      </p>
      <p className="mt-3 max-w-[70ch] text-sm text-dim">
        The <strong className="text-ink">COUNTERFACTUAL</strong> badge means the
        history is real and the position was never held. That is Showcase Mode,
        the default here.
      </p>
    </>
  );
}

function Step({
  n,
  title,
  href,
  note,
  simulated,
}: {
  n: number;
  title: string;
  href: string;
  note: string;
  simulated?: boolean;
}) {
  return (
    <li className="flex gap-3">
      <span className="tabular mt-0.5 shrink-0 rounded-full bg-brand-bg px-2 py-0.5 font-mono text-xs text-brand">
        {n}
      </span>
      <span className="min-w-0">
        <Link href={href} className="font-semibold">
          {title} &rarr;
        </Link>{" "}
        <Pill tone={simulated ? "unverified" : "pass"}>
          {simulated ? "Simulated" : "Real"}
        </Pill>
        <span className="mt-1 block max-w-[62ch] text-sm text-dim">{note}</span>
      </span>
    </li>
  );
}
