/**
 * One labelled input, shared by the two escrow surfaces.
 *
 * It lived inside `EscrowConsole` while there was one of them.
 */
export function EscrowField({
  label,
  value,
  onChange,
  placeholder,
  width = "w-full",
  note,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  width?: string;
  note?: string;
}) {
  return (
    <label className="block text-xs">
      <span className="text-faint">{label}</span>
      <input
        className={`mt-1 block ${width} rounded-sm border border-line bg-panel px-2 py-1.5 font-mono text-xs text-ink`}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      {note && <span className="mt-1 block text-faint">{note}</span>}
    </label>
  );
}
