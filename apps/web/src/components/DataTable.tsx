export interface Row {
  label: React.ReactNode;
  value: React.ReactNode;
  /** Optional third column: where the number came from, or what qualifies it. */
  note?: React.ReactNode;
  tone?: string;
}

/**
 * A metric table that a screen reader and a 320px phone can both use.
 *
 * The table it replaces was a bare `<table>` of `<td>` pairs: no `<caption>`,
 * no `<th>`, no `scope`, so nothing announced what the columns were or which
 * cell labelled which. It also had no horizontal overflow, and the left column
 * carries strings like "adverse selection (upper bound)" while the right
 * carries "17 mint · 23 recentre · 16 pull" — which collide well before 360px.
 *
 * The scroll container is focusable and labelled because a region that scrolls
 * only under a pointer is unreachable by keyboard.
 */
export function DataTable({
  caption,
  rows,
  hideCaption = true,
  columns = ["Metric", "Value"],
}: {
  caption: string;
  rows: Row[];
  hideCaption?: boolean;
  columns?: [string, string] | [string, string, string];
}) {
  const hasNote = rows.some((r) => r.note !== undefined);

  return (
    <div
      role="region"
      aria-label={caption}
      tabIndex={0}
      className="overflow-x-auto rounded-sm"
    >
      <table className="w-full border-collapse text-sm">
        <caption className={hideCaption ? "visually-hidden" : "mb-2 text-left text-sm text-dim"}>
          {caption}
        </caption>
        <thead className="visually-hidden">
          <tr>
            <th scope="col">{columns[0]}</th>
            <th scope="col">{columns[1]}</th>
            {hasNote && <th scope="col">{columns[2] ?? "Note"}</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-line last:border-b-0">
              <th
                scope="row"
                className="py-1.5 pr-4 text-left font-normal text-dim align-baseline"
              >
                {row.label}
              </th>
              <td
                className={`tabular py-1.5 text-right align-baseline whitespace-nowrap ${row.tone ?? ""}`}
              >
                {row.value}
              </td>
              {hasNote && (
                <td className="py-1.5 pl-4 text-right align-baseline text-xs text-faint">
                  {row.note}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
