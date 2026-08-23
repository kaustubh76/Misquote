/**
 * The words that replace the skeletons for a screen reader.
 *
 * `Skeleton.tsx` marks every placeholder `aria-hidden`, on the grounds that a
 * screen reader reading out a dozen empty boxes is worse than silence. Its
 * docstring then promised the wait was "announced in words instead — see the
 * `role="status"` region in a view wrapper".
 *
 * No such wrapper existed, and there was no status region anywhere. The
 * skeletons were hidden and nothing was said in their place, so a screen-reader
 * user got silence and then, abruptly, a full page. `test_comment_references`
 * caught the dangling filename; the missing announcement was behind it.
 *
 * ## Why `Loadable` exists rather than six copies of the pattern
 *
 * The sibling relationship is the whole trick. `aria-busy="true"` tells
 * assistive technology to defer changes inside that subtree, so a status region
 * nested *within* the busy container stays quiet until the load it describes has
 * already finished — announcing "loading" at the exact moment loading stops.
 *
 * That is a subtle enough invariant that re-establishing it by hand on every
 * page is how it comes to be wrong on one of them. It lives here instead, in one
 * component, where a test can hold it.
 */

export function LoadingStatus({
  loading,
  what = "content",
}: {
  loading: boolean;
  what?: string;
}) {
  return (
    <div role="status" aria-live="polite" className="sr-only">
      {loading ? `Loading ${what}.` : `${what} loaded.`}
    </div>
  );
}

/**
 * A busy region and the announcement that describes it, correctly adjacent.
 */
export function Loadable({
  loading,
  what,
  children,
  className = "",
}: {
  loading: boolean;
  what: string;
  children: React.ReactNode;
  /**
   * Applied to the content container, which is where a page sets its measure.
   *
   * `<main>` is `max-w-6xl` because the nav and the dashboard-shaped pages need
   * that width. A page of running prose does not: at 1280px it produced lines
   * of well over a hundred characters, and the pages worst affected are the
   * ones a reader is most expected to read end to end — the assumption sheet,
   * the method, the vector corpus. The measure belongs to the page rather than
   * to the layout, and this is the seam it hangs on.
   */
  className?: string;
}) {
  return (
    <>
      <LoadingStatus loading={loading} what={what} />
      <div aria-busy={loading} className={className}>
        {children}
      </div>
    </>
  );
}
