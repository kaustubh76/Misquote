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
      {/* `break-all` because the only note this takes today is a 32-byte
          hash, and a 66-character string with no break opportunity sets its
          container's min-content width — the row was 462px wide inside a 390px
          viewport when `/registry` did the same thing with a transaction
          hash. */}
      {note && <span className="mt-1 block font-mono break-all text-faint">{note}</span>}
    </label>
  );
}
