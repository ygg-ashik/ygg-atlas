import type { OverviewBreakdown } from '@/api/overview';
import { formatKpi } from '../format';
import { SourceChip } from './source-chip';

/** Top-N table (DESIGN.md › Dashboard): tabular figures, accent bars grow in staggered by 60ms. */
export function BreakdownCard({ breakdown }: { breakdown: OverviewBreakdown }) {
  const max = Math.max(...breakdown.rows.map((r) => r.value), 1);
  return (
    <div className="rounded-card bg-card px-[18px] py-4 shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_2px_rgba(0,0,0,0.04)]">
      <h3 className="mb-2.5 font-serif text-section text-ink">
        Top {breakdown.name.toLowerCase()}
      </h3>
      <table className="tabular w-full text-[13.5px]">
        <tbody>
          {breakdown.rows.map((r, i) => (
            <tr key={r.label} className="border-b border-border/50 last:border-0">
              <td className="py-2 pr-2 text-body">{r.label}</td>
              <td className="py-2 pr-3 text-right text-ink">
                {formatKpi(r.value, breakdown.unit)}
              </td>
              <td aria-hidden className="w-[36%] py-2">
                <div className="h-1.5 overflow-hidden rounded-full bg-primary/15">
                  <div
                    data-bar
                    className="h-full origin-left animate-[grow_900ms_cubic-bezier(.22,1,.36,1)_both] rounded-full bg-primary"
                    style={{
                      width: `${(Math.max(r.value, 0) / max) * 100}%`,
                      animationDelay: `${100 + i * 60}ms`,
                    }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3">
        <SourceChip provenance={breakdown.provenance} />
      </div>
    </div>
  );
}
