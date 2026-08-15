"use client";

import { createContext, useContext } from "react";

/**
 * Heading level as a property of position, not of the call site.
 *
 * The bug this replaces: `CardHeader` hardcoded `<h2>`, and it renders inside
 * sections that already own an `<h2>`, so every card was a sibling of the
 * heading that introduced it rather than a child. `ErrorNotice` hardcoded
 * `<h3>` and mounted directly under the page `<h1>` on all seven views, so
 * every error state skipped a level — in exactly the situation where someone is
 * most likely to be navigating by headings.
 *
 * The obvious fix is a `level` prop. It was rejected: there are eleven
 * `CardHeader` call sites across five files, plus `NotBuiltCard`, `Refusal` and
 * `ErrorNotice`, and a prop turns correctness into a per-call-site obligation
 * with no feedback when it is wrong. That is the same shape as the defect being
 * fixed — a fact restated by hand in many places, drifting silently.
 *
 * A heading's level *is* its depth in the document. Putting it in context makes
 * the tree carry it, so `<Card>` inside `<Section>` is an h3 because it is
 * nested, not because somebody remembered.
 */
const LevelContext = createContext(2);

export function useHeadingLevel(): number {
  return useContext(LevelContext);
}

export function HeadingLevel({
  value,
  children,
}: {
  value: number;
  children: React.ReactNode;
}) {
  return (
    <LevelContext.Provider value={Math.min(6, Math.max(1, value))}>
      {children}
    </LevelContext.Provider>
  );
}

/**
 * A heading at whatever depth it finds itself.
 *
 * `level` is an escape hatch for the rare case a specific level is wanted. Its
 * presence in a diff is a visible claim someone can argue with, which is the
 * opposite of an invisible default.
 */
export function Heading({
  level,
  className,
  id,
  children,
}: {
  level?: number;
  className?: string;
  id?: string;
  children: React.ReactNode;
}) {
  const contextLevel = useHeadingLevel();
  const resolved = Math.min(6, Math.max(1, level ?? contextLevel));
  const Tag = `h${resolved}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";

  return (
    <Tag id={id} className={className}>
      {children}
    </Tag>
  );
}

/**
 * A titled region, which deepens the level for everything inside it.
 *
 * Replaces the hand-written `<section><h2 …>…</h2><p …>…</p>` triple repeated
 * about twenty times across the views, and is what makes nested cards land at
 * h3 without any call site saying so.
 */
export function Section({
  title,
  intro,
  className = "mt-8",
  headingClassName = "mb-4 text-lg font-semibold",
  children,
}: {
  title: React.ReactNode;
  intro?: React.ReactNode;
  className?: string;
  headingClassName?: string;
  children?: React.ReactNode;
}) {
  const level = useHeadingLevel();

  return (
    <section className={className}>
      <Heading className={headingClassName}>{title}</Heading>
      {intro && <p className="mt-2 mb-5 max-w-[68ch] text-sm text-dim">{intro}</p>}
      <HeadingLevel value={level + 1}>{children}</HeadingLevel>
    </section>
  );
}
