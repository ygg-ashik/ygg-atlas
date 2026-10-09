import { useState } from 'react';
import { type RowScope } from '@/api/admin-groups';
import { useScopeDimensions } from '@/api/hooks/use-row-field';
import { Button, FutureControl, Input, Select, Tag } from '@/ui';

interface RowScopeBuilderProps {
  value: RowScope | null;
  onChange: (scope: RowScope | null) => void;
}

function Preview() {
  return (
    <FutureControl label="Row scope">
      <Tag>country</Tag>
      <Tag>= AE, SA</Tag>
      <Tag>+ dimension</Tag>
    </FutureControl>
  );
}

/** Phase-3 row scope for a resource allow. Reads `/meta/scope-dimensions`; until
 * that route ships it is shown disabled ("Arrives with row and field controls"). */
export function RowScopeBuilder({ value, onChange }: RowScopeBuilderProps) {
  const dims = useScopeDimensions();
  const [dimension, setDimension] = useState('');
  const [values, setValues] = useState('');
  if (!dims.data?.available) return <Preview />;
  const names = [...new Set(dims.data.data.map((d) => d.dimension))];
  const scope = value ?? {};
  const add = () => {
    const list = values
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean);
    if (!dimension || !list.length) return;
    onChange({ ...scope, [dimension]: list });
    setValues('');
  };
  const remove = (key: string) => {
    const { [key]: _gone, ...rest } = scope;
    onChange(Object.keys(rest).length ? rest : null);
  };
  return (
    <div className="rounded-md border border-border px-3.5 py-3">
      <div className="mb-1.5 text-label font-medium text-ink">Row scope</div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {Object.entries(scope).map(([k, v]) => (
          <button key={k} type="button" onClick={() => remove(k)} aria-label={`Remove ${k}`}>
            <Tag mono>
              {k} = {v.join(', ')} ✕
            </Tag>
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label="Dimension"
          value={dimension}
          onChange={(e) => setDimension(e.target.value)}
        >
          <option value="">Dimension</option>
          {names.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </Select>
        <Input
          aria-label="Values"
          className="w-40 font-mono"
          placeholder="AE, SA or $self"
          value={values}
          onChange={(e) => setValues(e.target.value)}
        />
        <Button type="button" variant="pill" size="sm" onClick={add}>
          Add
        </Button>
      </div>
    </div>
  );
}
