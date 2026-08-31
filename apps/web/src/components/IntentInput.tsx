"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/Button";
import { routeIntent } from "@/lib/categories";
import type { AgentRef } from "@/lib/artifacts";

/**
 * "What do you want handled?" — the one input `Readme.md` §1 promises.
 *
 * It had never existed. §1 describes "landing with one input … → routes to one
 * of four categories", and the landing page had three buttons and no field; the
 * only five inputs on the whole site were a wallet box and four lookups.
 *
 * ## Why this shows its working instead of just navigating
 *
 * The router is a keyword table in `lib/categories.ts`, and on a site whose
 * argument is that every answer traces to something, an input that silently
 * teleports you somewhere is the wrong shape even when it is right. So a match
 * says which words it matched on, and the reader can disagree before clicking.
 *
 * ## Why a miss is not an error
 *
 * `routeIntent` returns null for no match **and for a tie**, and this renders
 * both as the same thing: all four categories, one click away. That is not a
 * failure — it is the category index, which is where the button beside this
 * field already goes.
 *
 * Guessing would be worse than useless here. Picking one of two equally-matched
 * categories is a coin toss presented as a routing decision, which is the
 * behaviour this project is named after.
 */
export function IntentInput({ agents }: { agents: readonly AgentRef[] | undefined }) {
  const [text, setText] = useState("");
  const [asked, setAsked] = useState(false);

  const intent = asked ? routeIntent(text, agents) : null;
  const missed = asked && text.trim().length >= 2 && !intent;

  return (
    <form
      className="rise-4 mt-6"
      onSubmit={(event) => {
        event.preventDefault();
        setAsked(true);
      }}
    >
      <label htmlFor="intent" className="block text-sm font-semibold text-ink">
        What do you want handled?
      </label>
      <div className="mt-2 flex flex-wrap gap-2">
        <input
          id="intent"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setAsked(false);
          }}
          placeholder="keep my liquidity in range"
          className="min-w-0 flex-1 rounded-md border border-glass-line bg-glass px-3 py-2.5 text-sm text-ink transition-colors placeholder:text-faint focus:border-brand focus:shadow-[inset_3px_0_0_0_var(--brand)]"
        />
        <Button type="submit" disabled={text.trim().length < 2}>
          Route it
        </Button>
      </div>

      {intent && (
        <p className="mt-3 mb-0 text-sm text-dim">
          That reads as{" "}
          <Link href={`/category/${intent.slug}`} className="font-semibold">
            {intent.category} &rarr;
          </Link>{" "}
          <span className="text-faint">
            on {intent.matched.map((word) => `“${word}”`).join(", ")}
          </span>
          {/* Navigating on submit would hide the one thing worth seeing: which
              word decided it. The link is the action. */}
        </p>
      )}

      {missed && (
        <p className="mt-3 mb-0 text-sm text-dim">
          Nothing in that matched one category more than another, so this is not
          going to guess.{" "}
          <Link href="/category" className="font-semibold">
            All four &rarr;
          </Link>
        </p>
      )}
    </form>
  );
}
