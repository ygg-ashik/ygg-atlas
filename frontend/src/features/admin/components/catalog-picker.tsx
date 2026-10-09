import { type CatalogResources } from '@/api/catalog-admin';
import { useCatalogResources } from '@/api/hooks/use-catalog-resources';
import { useEffect, useId, useRef } from 'react';
import { CatalogCombobox, ErrorNotice, FieldError, type CatalogOption } from '@/ui';

/** Every grantable path: a source and an entity as `…/*`, each item exactly. */
export function catalogOptions(catalog: CatalogResources | undefined): CatalogOption[] {
  if (!catalog) return [];
  return catalog.sources.flatMap((s) => [
    { value: `${s.id}/*`, label: `${s.name} · everything`, kind: 'source' as const },
    ...s.entities.flatMap((e) => [
      { value: `${e.path}/*`, label: `${e.name} · all`, kind: 'entity' as const },
      ...e.items.map((i) => ({ value: i.path, label: i.name, kind: 'metric' as const })),
    ]),
  ]);
}

interface CatalogPickerProps {
  value: string;
  onChange: (path: string) => void;
  /** Inline error; the combobox is marked invalid and described by it. */
  error?: string;
}

/** The ui combobox owns its input; wire the hint and error to it for assistive tech. */
function useDescribedInput(hintId: string, errorId: string | null) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const input = ref.current?.querySelector('input');
    if (!input) return;
    input.setAttribute('aria-describedby', errorId ? `${hintId} ${errorId}` : hintId);
    if (errorId) input.setAttribute('aria-invalid', 'true');
    else input.removeAttribute('aria-invalid');
  });
  return ref;
}

/** The grant target picker: only real catalog paths (from the plugin registry) can be chosen. */
export function CatalogPicker({ value, onChange, error }: CatalogPickerProps) {
  const id = useId();
  const errorId = error ? `${id}-error` : null;
  const ref = useDescribedInput(`${id}-hint`, errorId);
  const catalog = useCatalogResources();
  const options = catalogOptions(catalog.data);
  if (catalog.isError) {
    return (
      <ErrorNotice
        title="Couldn't load the catalog"
        onRetry={() => void catalog.refetch()}
        retrying={catalog.isFetching}
      >
        Grant targets come from the catalog, so nothing can be picked until it loads.
      </ErrorNotice>
    );
  }
  const label = options.find((o) => o.value === value)?.label;
  return (
    <div ref={ref} className="grid gap-1.5">
      <CatalogCombobox label="Target" options={options} value={value} onValueChange={onChange} />
      <p id={`${id}-hint`} className="text-xs text-muted-foreground">
        {value ? (
          <>
            {label ?? value} · patterns ending in <span className="font-mono">/*</span> cover
            everything under them
          </>
        ) : (
          'Filled from the plugin registry; only real catalog paths can be granted.'
        )}
      </p>
      {errorId && <FieldError id={errorId}>{error}</FieldError>}
    </div>
  );
}
