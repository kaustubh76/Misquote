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

/* Two sizes, because the site already had two and they were drifting: the
   quote submit was `px-4 py-2.5` and the per-pool replay beside a card header
   was `px-3 py-1.5`. Both are real, so both are named here rather than
   re-invented at each call site. */
export type ButtonSize = "md" | "sm";

const SIZE: Record<ButtonSize, string> = {
  md: "gap-2 px-4 py-2.5 text-sm",
  sm: "gap-1.5 px-3 py-1.5 text-sm",
};

const TONE: Record<ButtonTone, string> = {
  primary:
    "border-transparent bg-brand text-brand-ink shadow-elev-brand " +
    "[box-shadow:inset_0_1px_0_0_var(--glass-hi),var(--elev-brand)] " +
    "hover:opacity-90 hover:[box-shadow:inset_0_1px_0_0_var(--glass-hi),0_0_0_3px_var(--brand-bg),var(--elev-brand)]",
  secondary:
    "surface border-glass-line bg-glass text-ink hover:border-brand hover:text-brand",
};

/*
 * `href` or `onClick`, and never both.
 *
 * This took `href` only, so every actual `<button>` on the site was a
 * hand-written class string at its call site, and the three that are plainly
 * buttons had already drifted apart: the `/quote` submit was `px-4 py-2.5` with
 * `transition-opacity` and `disabled:opacity-45`, the per-pool replay beside it
 * was `px-3 py-1.5` with the same opacity rule and no shadow, and `error.tsx`
 * was `rounded-sm` on `--panel` with an accent hover and no disabled state at
 * all. Three renderings of one control. Those three now come from here.
 *
 * What stays hand-written is the chip family — `src/components/CompareToggle.tsx`,
 * the tray's removable agent chips, the `/assumptions` filter — and that is not
 * an omission. They are toggles carrying selected state, not actions, and
 * folding them in would mean a `tone` per state and a component that is two
 * things.
 *
 * Three arms, not two, and the third is the point: a submit button inside a
 * form has no `onClick` — the form's `onSubmit` is the handler — so an arm that
 * demanded one forced the `/quote` call site to pass `onClick={() => {}}`. A
 * type that has to be lied to is not checking anything. Written this way the
 * compiler takes a link, a click handler or a submit, and rejects a `<Button>`
 * that is none of the three and would render dead.
 */
type ButtonProps = {
  children: React.ReactNode;
  tone?: ButtonTone;
  size?: ButtonSize;
  className?: string;
} & (
  | { href: string; onClick?: never; type?: never; disabled?: never }
  | { href?: never; onClick: () => void; type?: "button"; disabled?: boolean }
  | { href?: never; type: "submit"; onClick?: () => void; disabled?: boolean }
);

export function Button({
  href,
  children,
  tone = "primary",
  size = "md",
  className = "",
  onClick,
  type = "button",
  disabled,
}: ButtonProps) {
  const shape =
    `inline-flex items-center rounded-md border font-medium no-underline ` +
    `transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${SIZE[size]}`;

  if (href === undefined) {
    return (
      <button
        type={type}
        onClick={onClick}
        disabled={disabled}
        className={`${shape} ${TONE[tone]} ${className}`}
      >
        {children}
      </button>
    );
  }

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
