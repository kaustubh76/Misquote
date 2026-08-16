import { Heading } from "@/components/Heading";

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
    <Tag className={`rounded-lg border border-line bg-panel p-6 ${className}`}>
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
