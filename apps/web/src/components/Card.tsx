export function Card({
  children,
  className = "",
  as: Tag = "section",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "section" | "article" | "div";
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
        <h2 className="m-0 text-md font-semibold">
          {href ? (
            <a href={href} className="text-ink no-underline hover:underline">
              {title}
            </a>
          ) : (
            title
          )}
        </h2>
      </div>
      {aside && <div className="shrink-0">{aside}</div>}
    </div>
  );
}
