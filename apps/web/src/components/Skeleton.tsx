/**
 * Placeholder geometry matching what is about to arrive.
 *
 * `aria-hidden` throughout: the loading state is announced once through the
 * live region, and a screen reader reading out a dozen empty boxes is worse
 * than silence. The pulse is disabled under `prefers-reduced-motion` by the
 * global rule in `globals.css`.
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
