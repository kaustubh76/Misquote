/**
 * The Tape Head: the event tape this product replays, at page scale.
 *
 * A server component with no state, no randomness and no `Date`, so it cannot
 * produce a hydration mismatch and cannot reach the filesystem —
 * `tests/web/test_client_boundary.py` holds the second half of that. All of the
 * geometry lives in `globals.css` under `.tape`; this file is the four boxes it
 * needs and a note on why each one exists.
 *
 * It renders zero text nodes, deliberately. `scripts/check-pages.mjs` loads
 * every one of the thirteen routes with `javaScriptEnabled: false` and asserts
 * a minimum character count of `document.body.innerText` — `/assumptions` alone
 * must produce 50,000. A backdrop that contributed so much as a `<title>` would
 * be helping to satisfy a floor that exists to measure the page, and a floor a
 * decoration can help satisfy has stopped measuring anything.
 *
 * What each mark is:
 *   wash    the light the page sits in, and nothing else
 *   base    the tape's baseline — the line the events are recorded against
 *   rail    the events: 1px ticks at irregular offsets, drifting into the head
 *   head    the reader, pinned at the content column's left gutter, blended
 *           rather than painted so a tick changes as it crosses
 *   grain   dither, which is the layer that actually kills gradient banding
 */
export function Backdrop() {
  return (
    <div className="tape" aria-hidden="true">
      <div className="tape__wash" />

      <div className="tape__top">
        <div className="tape__base" />
        <div className="tape__rail tape__rail--a" />
        <div className="tape__rail tape__rail--b" />
      </div>

      {/* The mirror. Fainter, shorter, ticks hanging the other way, and gone
          entirely below 640px where there is no margin left to run it in. */}
      <div className="tape__bottom">
        <div className="tape__base" />
        <div className="tape__rail tape__rail--c" />
      </div>

      <div className="tape__head" />
      <div className="tape__grain" />
    </div>
  );
}
