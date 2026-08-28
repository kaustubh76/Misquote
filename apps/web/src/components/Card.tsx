import { Heading } from "@/components/Heading";

/*
 * `bg-glass` rather than `bg-panel`, and that is the whole change.
 *
 * `--panel` is opaque, which was correct while the page behind it was one flat
 * fill and there was nothing to see through to. There is now: `.tape` in
 * globals.css draws a field behind every route, and an opaque card is a lid on
 * it. `--glass` is `--panel` at 85% over `--bg`, which composites to a colour
 * lying between the two surfaces every text token is already measured against
 * — see the note on the token, which is why no contrast test moved.
 *
 * `shadow-elev-1` gives way to `.surface`, which is the same shadow plus a 1px
 * inset hairline along the top edge. A translucent panel needs a lit side; an
 * opaque one got that from its border.
 */

/**
 * `as` offers no `"div"`, on purpose.
 *
 * Both landmarks here are announced: `section` is one when it has an accessible
 * name, `article` is one unconditionally, and the two callers that pass
 * `as="article"` are rendering a self-contained item in a list of peers. `div`
 * was offered and never taken — it is the one choice that removes the card from
 * the document outline entirely, so a caller reaching for "no wrapper semantics"
 * would silently make the card unnavigable rather than get a plain box.
 */
export function Card({
  children,
  className = "",
  as: Tag = "section",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "section" | "article";
}) {
  return (
    <Tag
      className={`surface rounded-lg border border-glass-line bg-glass p-6 ${className}`}
    >
      {children}
    </Tag>
  );
}

export function CardHeader({
  title,
  eyebrow,
  aside,
  href,
}: {
  title: React.ReactNode;
  eyebrow?: React.ReactNode;
  aside?: React.ReactNode;
  href?: string;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && (
          <div className="mb-1 font-mono text-xs tracking-wide text-faint uppercase">
            {eyebrow}
          </div>
        )}
        <Heading className="m-0 text-md font-semibold">
          {href ? (
            <a href={href} className="text-ink no-underline hover:underline">
              {title}
            </a>
          ) : (
            title
          )}
        </Heading>
      </div>
      {/* `max-w-full` beside `shrink-0`, and the pair is the point.
          `shrink-0` says a badge must not be squeezed narrower than its own
          text, which is right. But a flex item that cannot shrink and has no
          maximum sits at its max-content width forever, so the moment a second
          badge joined the first — `TapeSource` beside the counterfactual
          warning on every LP card — this row measured 403px inside a 347px
          card and scrolled the whole document sideways at 390px. The aside's
          own `flex-wrap` was there to handle exactly this and could never fire,
          because nothing ever told it a width it had to fit in.

          Capped rather than allowed to shrink: the badges wrap onto a second
          line at full size instead of being compressed to fit on one. Found by
          `make web-check`, which is the only check that lays anything out.
          `AgentCard` carries a `min-w-0` for the same family of defect — a flex
          or grid item sized by its own content, invisible at 1280 and pushing
          the document sideways at 390. */}
      {aside && <div className="max-w-full shrink-0">{aside}</div>}
    </div>
  );
}
