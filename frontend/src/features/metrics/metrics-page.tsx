// src/features/metrics/metrics-page.tsx
import { useLocation } from 'react-router-dom';
import { Toolbar } from '@/ui';
import type { CatalogSource } from '@/api/atlas';
import { useMetricsCatalog } from '@/api/hooks/use-atlas';
import { askHref } from './ask';
import { CatalogRow } from './catalog-row';
import { FUNNEL_META, metricMeta } from './catalog-meta';

/** Every governed metric Atlas can answer with (DESIGN.md › inset-list). */
export function MetricsPage() {
  const { data, isLoading, isError } = useMetricsCatalog();
  const target = useLocation().hash.replace(/^#/, '');

  return (
    <div className="relative h-full">
      <Toolbar title="Metrics" />
      <div className="absolute inset-0 overflow-y-auto">
        <div className="mx-auto max-w-[760px] px-6 pb-16 pt-[84px]">
          <h2 className="font-serif text-display text-ink">Metrics</h2>
          <p className="mb-6 mt-1 text-muted-foreground">
            Every governed metric Atlas can answer with. Open one to see its definition.
          </p>
          {isLoading && <p className="text-label text-muted-foreground">Loading catalog…</p>}
          {isError && (
            <p role="alert" className="text-label text-muted-foreground">
              The catalog couldn’t be loaded. Try again in a moment.
            </p>
          )}
          {data?.sources.map((source) => (
            <SourceGroup key={source.id} source={source} target={target} />
          ))}
        </div>
      </div>
    </div>
  );
}

function SourceGroup({ source, target }: { source: CatalogSource; target: string }) {
  const headingId = `src-${source.id}`;
  return (
    <section className="mb-6" aria-labelledby={headingId}>
      <h3 id={headingId} className="px-1 pb-2 font-serif text-section text-ink">
        {source.name}
      </h3>
      <ul className="overflow-hidden rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.6)]">
        {source.metrics.map((m) => (
          <CatalogRow
            key={m.id}
            anchor={`metric-${m.id}`}
            name={m.name}
            id={m.id}
            description={m.description}
            meta={metricMeta(m)}
            ask={askHref(m)}
            targeted={target === `metric-${m.id}`}
          />
        ))}
        {source.funnels.map((f) => (
          <CatalogRow
            key={f.id}
            anchor={`metric-${f.id}`}
            name={f.name}
            id={f.id}
            description={f.description}
            meta={FUNNEL_META}
            ask={askHref(f)}
            targeted={target === `metric-${f.id}`}
          />
        ))}
      </ul>
    </section>
  );
}
