import type { Metadata } from "next";
import { Backdrop } from "@/components/Backdrop";
import { CompareTray } from "@/components/CompareTray";
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

  /**
   * Where a relative image URL resolves from.
   *
   * `og:image` has to be absolute for a crawler to fetch it, and Next builds it
   * against this. `NEXT_PUBLIC_SITE_URL` is a build-time value here and that is
   * correct, unlike the API base — `lib/api.ts` explains at length why *that*
   * one may not bake in, and the difference is real: the API host is a runtime
   * property of a deployment a static export may be repointed at, and the
   * canonical URL of that export is a property of the build itself.
   *
   * The default is the deployed host rather than localhost, and that is the
   * fix for a chicken-and-egg: a card is only worth having if it resolves, and
   * requiring an environment variable to make it resolve means every build that
   * forgets one ships a card pointing at a machine nobody else can reach. This
   * project has one canonical URL, the repository can know it, and
   * `NEXT_PUBLIC_SITE_URL` still overrides for a fork or a preview.
   */
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://misquote.vercel.app",
  ),

  /**
   * The card a paste of this link unfurls into.
   *
   * There was none at all — no `og:*`, no `twitter:*` — so every share of this
   * URL rendered as a bare link. On a project whose brief was to showcase
   * itself, that is the one surface guaranteed to be seen before the site.
   *
   * `title` and `description` are not restated: the defaults above are the
   * page's own, and a second copy is a second thing to keep true. The image
   * comes from `opengraph-image.tsx`, which Next wires in by convention.
   */
  openGraph: {
    type: "website",
    siteName: "Misquote",
    locale: "en",
    // `/opengraph-image.png`, not the `/opengraph-image` route Next wires in by
    // convention, and the extension is the entire reason. The generated route
    // exports as a file with no suffix, and `make web-static` — the command a
    // judge is told to run — serves it through `python3 -m http.server`, which
    // types by extension and answers `application/octet-stream`. Slack and
    // Discord sniff and cope; Twitter and LinkedIn are documented not to.
    // Measured, not assumed: `curl -I` on the export returns exactly that.
    images: ["/opengraph-image.png"],
  },
  twitter: {
    // `summary_large_image`, because the card is a 1200×630 figure. `summary`
    // would crop the band mark out of its own share card.
    card: "summary_large_image",
    images: ["/opengraph-image.png"],
  },
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
        {/* First child, and fixed at `z-index: -1`. It is visible only because
            `body` carries the page background and a root-element background
            propagates to the canvas, which paints behind negative-z children —
            so nothing here may give `html` or `body` a stacking context. See
            the note above `.tape` in globals.css. */}
        <Backdrop />

        <a href="#main" className="skip-link">
          Skip to content
        </a>

        <Nav />
        <RouteAnnouncer />

        {/* tabIndex -1 so the skip link actually moves focus. Without it the jump
            is left to browser heuristics, which is the one thing a skip link
            exists to avoid. */}
        <main id="main" tabIndex={-1} className="mx-auto max-w-6xl px-5 pt-10 pb-24">
          {children}
        </main>

        {/* After `<main>`, not before it. A fixed bar ahead of the content in
            the tab order is the thing the skip link exists to route around, and
            mounting it here also keeps it out of every per-page render — so the
            heading-outline test never sees a tray heading between a page's h1
            and its cards. It renders nothing until something is selected. */}
        <CompareTray />

        {/* Names the directory, not three files.
            It listed `index.json`, `warden.json` and `advantage.json` and said
            "every number on this site is in them". There are thirteen: every
            figure on /status is in `status.json`, every one on /vectors is in
            `vectors.json`, and so on. A reader with JavaScript off followed
            that instruction to three files and was told that was all of them.

            It also said the site "needs JavaScript to fetch", which read as a
            fact about the architecture rather than a fact about `useEffect`.
            Two routes render server-side now, so it says which. And it no
            longer ends by telling a reader without JavaScript that the answer
            is printed in a footer for readers who have it. */}
        <noscript>
          <div className="mx-auto max-w-5xl px-5 pb-16 text-sm text-dim">
            The overview and the agent pages render here without JavaScript. Every
            other page needs it to fetch its numbers, and shows its heading and
            lede meanwhile. The artifacts are plain files either way:{" "}
            <code className="font-mono">artifacts/</code> holds one per page —{" "}
            <code className="font-mono">index.json</code> lists the agents, and each page
            names the file it reads in its footer.
          </div>
        </noscript>
      </body>
    </html>
  );
}
