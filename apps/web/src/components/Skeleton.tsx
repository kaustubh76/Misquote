/**
 * Placeholder geometry matching what is about to arrive.
 *
 * `aria-hidden` throughout: a screen reader reading out a dozen empty boxes is
 * worse than silence, and the wait is announced in words instead — by the
 * `role="status"` region in `LoadingStatus.tsx`, which `Loadable` places as a
 * *sibling* of the `aria-busy` container rather than a child of it.
 *
 * That sibling relationship is the whole trick, and it is why `Loadable` owns
 * both halves: `aria-busy="true"` tells assistive tech to defer changes inside
 * the subtree, so a status region nested within it would say nothing until the
 * load it describes had already finished.
 *
 * This comment previously named `ArtifactView.tsx`, a file that has never
 * existed, and the announcement it promised had never been built — so the
 * skeletons were hidden and nothing was said in their place.
 *
 * The pulse is disabled under `prefers-reduced-motion` by the global rule in
 * `globals.css`.
 */
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`animate-pulse rounded-sm bg-neutral-bg ${className}`}
    />
  );
}

export function CardSkeleton() {
  return (
    <div className="rounded-lg border border-line bg-panel p-6" aria-hidden="true">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-3 h-5 w-28" />
      <Skeleton className="mt-4 h-16 w-full" />
      <div className="mt-4 space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-5/6" />
        <Skeleton className="h-3 w-4/6" />
      </div>
    </div>
  );
}
