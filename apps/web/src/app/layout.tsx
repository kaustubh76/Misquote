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
  // "traces to chain state" picked the flattering half of a contradiction the
  // site reports elsewhere as a failing gate: the agent artifacts are replayed
  // over indexed chain history, `advantage.json` is a synthetic tape, and
  // /status marks that UNVERIFIED. Each page states its own source in a banner;
  // the description no longer states one for all of them.
  description:
    "Every other marketplace misquotes you. This one shows its math: P25–P75 ranges where every number traces to a published artifact, each page saying whether its tape was chain history or synthetic, and no number at all where the evidence is too thin.",
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

        {/* Names the directory, not three files.
            It listed `index.json`, `warden.json` and `advantage.json` and said
            "every number on this site is in them". There are thirteen: every
            figure on /status is in `status.json`, every one on /vectors is in
            `vectors.json`, and so on. A reader with JavaScript off followed
            that instruction to three files and was told that was all of them. */}
        <noscript>
          <div className="mx-auto max-w-5xl px-5 pb-16 text-sm text-dim">
            This page renders precomputed JSON, which needs JavaScript to fetch. The
            artifacts are plain files and can be read directly:{" "}
            <code className="font-mono">artifacts/</code> holds one per page —{" "}
            <code className="font-mono">index.json</code> lists the agents, and each page
            names the file it reads in the footer it prints when JavaScript is on.
          </div>
        </noscript>
      </body>
    </html>
  );
}
