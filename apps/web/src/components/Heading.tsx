"use client";

import { createContext, useContext } from "react";
import { TickRule } from "@/components/TickRule";

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
  id,
  className = "mt-8",
  headingClassName = "mb-4 text-lg font-semibold",
  children,
}: {
  title: React.ReactNode;
  intro?: React.ReactNode;
  /**
   * An anchor, for a page long enough to be navigated within.
   *
   * `.scroll-anchor` comes with it rather than being left to the caller: the
   * header is `sticky top-0` and two rows tall, and `scroll-behavior` is smooth
   * globally, so an un-offset jump parks the target heading underneath the nav
   * and drops the reader into the middle of the section they asked for.
   */
  id?: string;
  className?: string;
  headingClassName?: string;
  children?: React.ReactNode;
}) {
  const level = useHeadingLevel();

  return (
    // `data-heading-scope` marks *this* element rather than every <section> in
    // the DOM, because `Card` defaults to rendering a <section> too. The outline
    // test keys off it to assert that everything inside a Section sits strictly
    // below the Section's own title.
    <section
      id={id}
      data-heading-scope=""
      className={`${id ? "scroll-anchor " : ""}${className}`}
    >
      {/* The glyph goes inside the heading rather than beside it, so
          `headingClassName` keeps meaning what its ~20 callers already pass —
          several set their own margin, and a flex row around the heading would
          have moved all of them. It is `aria-hidden` and renders no text, so
          the accessible name and `innerText` are both unchanged. */}
      <Heading className={headingClassName}>
        <TickRule lead />
        {title}
      </Heading>
      {intro && <p className="mt-2 mb-5 max-w-[68ch] text-sm text-dim">{intro}</p>}
      <HeadingLevel value={level + 1}>{children}</HeadingLevel>
    </section>
  );
}
