import { ImageResponse } from "next/og";

/**
 * The card a link to this site unfurls into.
 *
 * There was none — no `og:image`, no `og:title`, no `twitter:card` — so every
 * paste of this URL into Slack, Discord or a submission form rendered a bare
 * link. On a project whose brief was to showcase itself, that is the one
 * surface guaranteed to be seen before the site is.
 *
 * It draws the mark rather than a screenshot: the P25–P75 band with its median
 * tick, which is what `src/app/icon.svg` is, what `src/components/TickRule.tsx`
 * is at glyph scale, and what `src/components/Band.tsx` draws on every card
 * here. A product whose argument is "a quote is a range, not a point" should
 * unfurl as a range.
 *
 * ## Why this exports at all
 *
 * `ImageResponse` ships inside `next`, so this adds no dependency and no
 * build-time network call — it rasterises locally and lands in the export as a
 * static PNG. It needs `dynamic = "force-static"` to do that: without it the
 * build fails with "export const dynamic … not configured on route
 * /opengraph-image with output: export", which is the whole of what stood
 * between this site and having a share card.
 *
 * Satori, which renders this, supports flexbox and not grid, so every box below
 * is a flex row or column and every child that could collapse carries an
 * explicit `display: flex`.
 *
 * ## Why there is also a PNG in `public/`
 *
 * This route exports as a file with **no extension**, and `make web-static`
 * serves the export through `python3 -m http.server`, which types by extension
 * and answers `application/octet-stream`. Measured with `curl -I`, not assumed.
 * Slack and Discord sniff the magic bytes and cope; Twitter and LinkedIn
 * document that they will not.
 *
 * So `apps/web/public/opengraph-image.png` is the copy the metadata points at,
 * and this file is the source it is generated from. `make og` regenerates it —
 * the output is byte-identical across builds, so a stale copy is a diff rather
 * than a mystery. Committing a generated file is the pattern this repository
 * already uses for `public/artifacts/*.json`.
 */
export const dynamic = "force-static";
export const alt =
  "Misquote — every marketplace misquotes you. P25–P75 ranges, or nothing.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/* The tokens, resolved. `light-dark()` and `var()` mean nothing to a
   rasteriser, so these are the dark arm of globals.css written out — the theme
   a social card cannot ask the reader about. */
const BG = "#0b0d10";
const INK = "#e8eaed";
const DIM = "#9aa2ad";
const FAINT = "#808995";
const BRAND = "#d8b4fe";
const LINE = "#232830";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: BG,
          padding: 72,
        }}
      >
        {/* The tape, at the top edge — the backdrop this site is built on,
            reduced to the one thing a 1200×630 card can carry of it: irregular
            ticks on a baseline, drifting nowhere because a PNG does not move. */}
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          <div style={{ display: "flex", height: 26, alignItems: "flex-start", gap: 0 }}>
            {[
              14, 6, 22, 8, 10, 38, 12, 6, 16, 54, 8, 18, 10, 26, 6, 12, 44, 8,
              14, 6, 20, 62, 10, 8, 24, 12, 6, 34, 8, 16, 10, 48, 6, 18, 12, 8,
              28, 6, 14, 40,
            ].map((gap, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  width: 1,
                  height: i % 3 === 0 ? 18 : 10,
                  marginLeft: gap,
                  background: i % 3 === 0 ? "#3a4250" : "#2a3140",
                }}
              />
            ))}
          </div>
          <div style={{ display: "flex", height: 1, background: LINE }} />
        </div>

        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "flex",
              fontSize: 22,
              letterSpacing: 4,
              color: BRAND,
              textTransform: "uppercase",
            }}
          >
            Agent marketplace · BNB Chain
          </div>

          <div
            style={{
              display: "flex",
              marginTop: 22,
              fontSize: 82,
              lineHeight: 1.05,
              fontWeight: 700,
              letterSpacing: -2,
              color: INK,
            }}
          >
            Every marketplace misquotes you.
          </div>

          <div
            style={{
              display: "flex",
              marginTop: 24,
              fontSize: 27,
              lineHeight: 1.4,
              color: DIM,
              maxWidth: 900,
            }}
          >
            Every agent replayed on your positions, quoted as a P25–P75 range —
            and nothing at all where the evidence is too thin.
          </div>
        </div>

        {/* The mark. `--line` to P25, brand across the interquartile range,
            `--line` to P75, median tick at the centre: the same figure
            `TickRule` draws under the hero and `Band` draws on every card. */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          {/* Five flex children, and no absolute positioning — which took a
              correction. `position: absolute` inside this row resolved against
              the root's padding box rather than the row, so a tick placed at
              the axis midpoint landed 72px right of it, by exactly the page
              padding. Splitting the brand segment in half and letting the tick
              be an ordinary sibling puts it at the centre by construction.
              1056 = the 1200 card less 72 of padding on each side. */}
          <div style={{ display: "flex", alignItems: "center", height: 20 }}>
            <div style={{ display: "flex", height: 3, width: 264, background: LINE }} />
            <div style={{ display: "flex", height: 3, width: 262, background: BRAND }} />
            <div style={{ display: "flex", width: 4, height: 20, background: BRAND }} />
            <div style={{ display: "flex", height: 3, width: 262, background: BRAND }} />
            <div style={{ display: "flex", height: 3, width: 264, background: LINE }} />
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              marginTop: 16,
              fontSize: 20,
              color: FAINT,
            }}
          >
            <div style={{ display: "flex" }}>P25 — median — P75</div>
            <div style={{ display: "flex" }}>misquote · audit me</div>
          </div>
        </div>
      </div>
    ),
    size,
  );
}
