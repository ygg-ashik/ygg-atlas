import { useState } from 'react';
import { type RowScope } from '@/api/admin-groups';
import { useScopeDimensions } from '@/api/hooks/use-row-field';
import { type ScopeDimension } from '@/api/row-field';
import { Button, ErrorNotice, Input, Select, Skeleton, SkeletonRegion, Tag } from '@/ui';
import { scopeText } from '../review-lines';

interface RowScopeBuilderProps {
  value: RowScope | null;
  onChange: (scope: RowScope | null) => void;
  /** False for anything but a resource allow: the backend refuses a scope there. */
  applies: boolean;
}

const FRAME = 'rounded-md border border-border px-3.5 py-3';

interface DimensionOption {
  name: string;
  /** True when some declaring entity resolves `$self` for it. */
  self: boolean;
}

/** One option per dimension name; the backend decides which of them the
 * grant's target can be scoped by and says so on Apply. */
function dimensionOptions(dims: readonly ScopeDimension[]): DimensionOption[] {
  const byName = new Map<string, DimensionOption>();
  for (const d of dims) {
    const known = byName.get(d.dimension);
    byName.set(d.dimension, {
      name: d.dimension,
      self: (known?.self ?? false) || d.self_attribute !== null,
    });
  }
  return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** Row scope for a resource allow, from the dimensions enabled plugins
 * declare (`/meta/scope-dimensions`). Empty = all rows. */
export function RowScopeBuilder({ value, onChange, applies }: RowScopeBuilderProps) {
  if (!applies) {
    return (
      <p className={`${FRAME} text-caption text-muted-foreground`}>
        Row scope narrows a resource allow only; this grant has none.
      </p>
    );
  }
  return <ScopeEditor value={value} onChange={onChange} />;
}

function ScopeEditor({ value, onChange }: Omit<RowScopeBuilderProps, 'applies'>) {
  const dims = useScopeDimensions();
  const [dimension, setDimension] = useState('');
  const [values, setValues] = useState('');
  if (dims.isPending) {
    return (
      <SkeletonRegion label="scope dimensions" className={FRAME}>
        <Skeleton className="w-1/3" />
        <Skeleton className="mt-2 w-2/3" />
      </SkeletonRegion>
    );
  }
  if (dims.isError) {
    return (
      <ErrorNotice
        title="Couldn't load scope dimensions"
        onRetry={() => void dims.refetch()}
        retrying={dims.isFetching}
      >
        Without them the grant covers all rows.
      </ErrorNotice>
    );
  }
  const options = dimensionOptions(dims.data);
  const chosen = options.find((o) => o.name === dimension);
  const scope = value ?? {};
  const add = () => {
    const list = values
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean);
    if (!dimension || !list.length) return;
    onChange({ ...scope, [dimension]: [...new Set(list)] });
    setValues('');
  };
  const remove = (key: string) => {
    const { [key]: _gone, ...rest } = scope;
    onChange(Object.keys(rest).length ? rest : null);
  };
  return (
    <div className={FRAME}>
      <div className="mb-1.5 text-label font-medium text-ink">Row scope</div>
      {options.length === 0 ? (
        <p className="text-caption text-muted-foreground">
          No enabled data source declares scope dimensions, so grants cover all rows.
        </p>
      ) : (
        <>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {value ? (
              Object.entries(scope).map(([k, v]) => (
                <button key={k} type="button" onClick={() => remove(k)} aria-label={`Remove ${k}`}>
                  <Tag mono>{scopeText({ [k]: v })} ✕</Tag>
                </button>
              ))
            ) : (
              <span className="text-caption text-muted-foreground">All rows</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              aria-label="Dimension"
              value={dimension}
              onChange={(e) => setDimension(e.target.value)}
            >
              <option value="">Dimension</option>
              {options.map((o) => (
                <option key={o.name} value={o.name}>
                  {o.name}
                </option>
              ))}
            </Select>
            <Input
              aria-label="Values"
              className="w-40 font-mono"
              spellCheck={false}
              placeholder={chosen?.self ? 'AE, SA or $self' : 'AE, SA'}
              value={values}
              onChange={(e) => setValues(e.target.value)}
            />
            <Button type="button" variant="pill" size="sm" onClick={add}>
              Add
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
