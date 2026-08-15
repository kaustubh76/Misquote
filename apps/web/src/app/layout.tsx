import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import { RouteAnnouncer } from "@/components/RouteAnnouncer";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Misquote — agent marketplace for BNB Chain",
    template: "%s — Misquote",
  },
  description:
    "Every other marketplace misquotes you. This one shows its math: P25–P75 ranges where every number traces to chain state or a published assumption, and withholds the number when the evidence is too thin.",
  other: { "color-scheme": "dark light" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Render-blocking on purpose: it must run before the first paint or a
            pinned theme flashes the other one. See lib/theme.ts. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body>
        <a href="#main" className="skip-link">
          Skip to content
        </a>

        <Nav />
        <RouteAnnouncer />

        {/* tabIndex -1 so the skip link actually moves focus. Without it the jump
            is left to browser heuristics, which is the one thing a skip link
            exists to avoid. */}
        <main id="main" tabIndex={-1} className="mx-auto max-w-5xl px-5 pt-10 pb-24">
          {children}
        </main>

        <noscript>
          <div className="mx-auto max-w-5xl px-5 pb-16 text-sm text-dim">
            This page renders precomputed JSON, which needs JavaScript to fetch. The
            underlying artifacts are plain files and can be read directly at{" "}
            <code className="font-mono">artifacts/index.json</code>,{" "}
            <code className="font-mono">artifacts/warden.json</code> and{" "}
            <code className="font-mono">artifacts/advantage.json</code> — every number on
            this site is in them.
          </div>
        </noscript>
      </body>
    </html>
  );
}
