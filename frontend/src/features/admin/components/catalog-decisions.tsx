import { type CatalogDecision, type CatalogResources } from '@/api/catalog-admin';
import { useCatalogResources } from '@/api/hooks/use-catalog-resources';
import { ErrorNotice, SkeletonRegion, SkeletonRows, TreeList, type TreeNode } from '@/ui';
import { EffectPill } from './effect-pill';
import { CARD } from './surfaces';

function Verdict({ decision }: { decision?: CatalogDecision | null }) {
  if (!decision) return null;
  return (
    <>
      <span className="font-mono text-[11px] text-muted-foreground max-[699px]:hidden">
        {decision.origin ?? 'no grant'}
      </span>
      <EffectPill effect={decision.allowed ? 'allow' : 'deny'} />
    </>
  );
}

const mono = (text: string) => <span className="font-mono text-ink">{text}</span>;

function toNodes(catalog: CatalogResources): TreeNode[] {
  return catalog.sources.map((s) => ({
    id: s.id,
    label: mono(s.id),
    detail: s.name,
    children: s.entities.map((e) => ({
      id: e.path,
      label: mono(e.path.split('/').at(-1) ?? e.path),
      detail: e.name,
      trailing: <Verdict decision={e.decision} />,
      children: e.items.map((i) => ({
        id: i.path,
        label: mono(i.id),
        detail: i.name,
        trailing: <Verdict decision={i.decision} />,
      })),
    })),
  }));
}

/** The catalog outline with the target user's decision on every entity and item. */
export function CatalogDecisions({ userId, firstName }: { userId: string; firstName: string }) {
  const catalog = useCatalogResources(userId);
  const label = `What ${firstName} can see`;
  return (
    <div className={`${CARD} px-2 py-2.5`}>
      <p className="px-3 pb-1 pt-1.5 text-label font-medium text-ink">
        Catalog · {label.toLowerCase()}
      </p>
      {catalog.isPending && (
        <SkeletonRegion label="the catalog">
          <SkeletonRows count={4} />
        </SkeletonRegion>
      )}
      {catalog.isError && (
        <ErrorNotice
          title="Couldn't load the catalog"
          onRetry={() => void catalog.refetch()}
          retrying={catalog.isFetching}
        />
      )}
      {catalog.data && <TreeList variant="outline" label={label} nodes={toNodes(catalog.data)} />}
    </div>
  );
}
