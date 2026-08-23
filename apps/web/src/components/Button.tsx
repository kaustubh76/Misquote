import Link from "next/link";

/**
 * The primary action, in the one colour this palette reserves for actions.
 *
 * Before this the site's only call to action was a bordered grey box with a
 * blue link inside it — `rounded-md border border-line bg-panel … hover:border-accent`
 * hand-written on the landing page — which is indistinguishable at a glance
 * from the cards around it. A marketplace whose main verb is "hire this agent"
 * needs its verbs to look like verbs.
 *
 * `--brand` exists for exactly this and is deliberately not `--accent`: a
 * filled action must not read as a hyperlink, and a hyperlink must not read as
 * a filled action. Both clear AA against every surface, and `--brand-ink`
 * against the fill, asserted in `tests/web/test_theme_tokens.py`.
 *
 * Renders `next/link` for an internal href and `<a>` for anything external,
 * because `Link` on an off-site URL prefetches a route that does not exist.
 */
export type ButtonTone = "primary" | "secondary";

const TONE: Record<ButtonTone, string> = {
  primary:
    "border-transparent bg-brand text-brand-ink shadow-elev-brand hover:opacity-90",
  secondary:
    "border-line bg-panel text-ink hover:border-brand hover:text-brand",
};

export function Button({
  href,
  children,
  tone = "primary",
  className = "",
}: {
  href: string;
  children: React.ReactNode;
  tone?: ButtonTone;
  className?: string;
}) {
  const shape =
    "inline-flex items-center gap-2 rounded-md border px-4 py-2.5 text-sm font-medium no-underline transition-colors";
  const external = href.startsWith("http") || href.startsWith("mailto:");

  if (external) {
    return (
      <a href={href} className={`${shape} ${TONE[tone]} ${className}`}>
        {children}
      </a>
    );
  }

  return (
    <Link href={href} className={`${shape} ${TONE[tone]} ${className}`}>
      {children}
    </Link>
  );
}
