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
      {aside && <div className="shrink-0">{aside}</div>}
    </div>
  );
}
