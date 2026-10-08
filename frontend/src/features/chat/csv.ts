type Cell = string | number | null;

function cell(value: Cell): string {
  if (value === null) return '';
  let s = String(value);
  // CSV formula injection: prefix cells a spreadsheet would evaluate.
  if (typeof value === 'string' && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** RFC 4180 CSV (CRLF rows), safe to open in a spreadsheet. */
export function toCsv(columns: string[], rows: Cell[][]): string {
  return [columns, ...rows].map((r) => r.map(cell).join(',')).join('\r\n');
}

/** A lowercase, dash-separated `.csv` filename derived from a title. */
export function artifactFilename(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `${slug || 'artifact'}.csv`;
}
