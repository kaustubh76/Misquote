"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/ThemeToggle";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/advantage", label: "Advantage" },
  { href: "/methods", label: "Methods" },
  { href: "/assumptions", label: "Assumptions" },
  { href: "/registry", label: "Registry" },
  { href: "/vetting", label: "Vetting" },
  { href: "/status", label: "Status" },
] as const;

function isActive(pathname: string, href: string): boolean {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (href === "/") return path === "/";
  return path === href || path.startsWith(`${href}/`);
}

export function Nav() {
  const pathname = usePathname() ?? "/";

  return (
    <header className="sticky top-0 z-50 border-b border-line bg-bg/85 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center gap-4 px-5 py-3">
        <Link
          href="/"
          className="shrink-0 font-mono text-sm font-semibold tracking-tight text-ink no-underline"
        >
          Misquote
        </Link>

        {/* Overflows to a horizontal scroll rather than wrapping or truncating,
            so every route stays reachable at 320px. */}
        <nav aria-label="Primary" className="min-w-0 flex-1">
          {/* `overflow-x: auto` computes overflow-y to auto as well, so the box
              clips on both axes and ate the 2px focus ring at its 2px offset.
              The padding makes room inside the scroll box; the negative margin
              puts the layout back. CSS-only, so `make web-check` is its only
              guard. */}
          <ul className="flex list-none items-center gap-1 overflow-x-auto p-1.5 -m-1.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {LINKS.map((link) => {
              const active = isActive(pathname, link.href);
              return (
                <li key={link.href} className="shrink-0">
                  <Link
                    href={link.href}
                    aria-current={active ? "page" : undefined}
                    className={[
                      "block rounded-sm px-2.5 py-1.5 text-sm no-underline transition-colors",
                      active ? "bg-neutral-bg text-ink" : "text-dim hover:text-ink",
                    ].join(" ")}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="shrink-0">
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
