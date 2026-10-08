import { Download, X } from 'lucide-react';
import type { ArtifactBlock } from '@/api/chat';
import { Button } from '@/ui';
import { seriesFor, type SeriesPoint } from '../artifact-series';
import { artifactFilename, toCsv } from '../csv';
import { ProvenanceChips } from './provenance-chips';

const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

function exportCsv(artifact: ArtifactBlock) {
  const blob = new Blob([toCsv(artifact.columns, artifact.rows)], {
    type: 'text/csv;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = artifactFilename(artifact.title);
  a.click();
  // Revoke after the click has been handled, or some browsers cancel the download.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Accent bars grow in staggered by 60ms (DESIGN.md › Dashboard Top-N). */
function ArtifactBars({ series }: { series: SeriesPoint[] }) {
  if (series.length === 0) return null;
  const max = Math.max(...series.map((p) => p.value), 1);
  return (
    <div className="space-y-1.5 py-1" aria-hidden>
      {series.map((p, i) => (
        <div
          key={`${i}-${p.label}`}
          className="grid grid-cols-[minmax(0,40%)_1fr] items-center gap-3 text-caption text-muted-foreground"
        >
          <span className="truncate">{p.label}</span>
          <div className="h-4 overflow-hidden rounded-md bg-primary/10">
            <div
              data-testid="artifact-bar"
              className="h-full origin-left animate-[grow_900ms_cubic-bezier(.22,1,.36,1)_both] rounded-md bg-primary"
              style={{
                width: `${(Math.max(p.value, 0) / max) * 100}%`,
                opacity: 1 - i * (0.55 / series.length),
                animationDelay: `${i * 60}ms`,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function cellText(v: string | number | null): string {
  if (typeof v === 'number') return fmt.format(v);
  return v ?? '—';
}

function ArtifactTable({ artifact }: { artifact: ArtifactBlock }) {
  return (
    <div className="max-w-full overflow-x-auto">
      <table className="tabular w-full text-[13.5px]">
        <thead>
          <tr>
            {artifact.columns.map((c, i) => (
              <th
                key={c}
                scope="col"
                className={`border-b border-border px-1 py-2 text-caption font-medium text-muted-foreground ${i > 0 ? 'text-right' : 'text-left'}`}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {artifact.rows.map((r, ri) => (
            <tr key={ri} className="border-b border-border/50 last:border-0">
              {r.map((v, ci) => (
                <td
                  key={ci}
                  className={`px-1 py-2 ${ci > 0 ? 'text-right text-ink' : 'text-body'}`}
                >
                  {cellText(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ArtifactPanelProps {
  artifact: ArtifactBlock;
  onClose: () => void;
}

/** Claude-style artifact panel (DESIGN.md › artifact-panel): data on a solid
 * surface, never on glass. Chart, table, provenance and CSV export. */
export function ArtifactPanel({ artifact, onClose }: ArtifactPanelProps) {
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto rounded-shell bg-card px-5 py-[18px] shadow-[0_0_0_1px_hsl(var(--border)),0_20px_60px_rgba(0,0,0,0.14)]">
      <div className="flex items-start gap-2.5">
        <h3 className="min-w-0 flex-1 font-serif text-title text-ink">{artifact.title}</h3>
        <Button variant="ghost" size="icon" aria-label="Close artifact" onClick={onClose}>
          <X />
        </Button>
      </div>
      <ProvenanceChips provenance={[artifact.provenance]} />
      <ArtifactBars series={seriesFor(artifact)} />
      <ArtifactTable artifact={artifact} />
      {artifact.unit && <p className="text-caption text-muted-2">Values in {artifact.unit}.</p>}
      <div className="mt-auto flex gap-2 pt-2">
        <Button variant="pill" size="sm" onClick={() => exportCsv(artifact)}>
          <Download /> Export CSV
        </Button>
      </div>
    </div>
  );
}
