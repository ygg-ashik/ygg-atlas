import type { ArtifactBlock } from '@/api/chat';

export interface SeriesPoint {
  label: string;
  value: number;
}

type Cell = ArtifactBlock['rows'][number][number];

const text = (c: Cell | undefined): string => (c === null || c === undefined ? '—' : String(c));

function point(type: ArtifactBlock['artifact_type'], row: Cell[]): SeriesPoint | null {
  if (type === 'comparison') {
    const [period, start, end, value] = row;
    if (typeof value !== 'number') return null;
    return { label: `${text(period)} · ${text(start)} → ${text(end)}`, value };
  }
  const [label, value] = row;
  return typeof value === 'number' ? { label: text(label), value } : null;
}

/** Which columns become the bar chart, per artifact type (built from tool output). */
export function seriesFor(artifact: ArtifactBlock): SeriesPoint[] {
  return artifact.rows
    .map((r) => point(artifact.artifact_type, r))
    .filter((p): p is SeriesPoint => p !== null);
}
