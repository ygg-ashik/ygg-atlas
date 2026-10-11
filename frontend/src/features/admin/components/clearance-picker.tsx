import { useCapabilityCatalog } from '@/api/hooks/use-capability-catalog';
import { ErrorNotice, Select } from '@/ui';

interface ClearancePickerProps {
  /** The chosen clearance code, or null for a resource grant. */
  value: string | null;
  onChange: (code: string | null) => void;
}

/** Field clearances from `/meta/capabilities`: a clearance grant lets its
 * holders see the labels that class masks. Empty while the catalog loads. */
export function ClearancePicker({ value, onChange }: ClearancePickerProps) {
  const catalog = useCapabilityCatalog();
  const clearances = catalog.data?.clearances ?? [];
  if (catalog.isError) {
    return (
      <ErrorNotice
        title="Couldn't load clearances"
        onRetry={() => void catalog.refetch()}
        retrying={catalog.isFetching}
      />
    );
  }
  const chosen = clearances.find((c) => c.code === value);
  return (
    <label className="grid gap-1.5 rounded-md border border-border px-3.5 py-3">
      <span className="text-label font-medium text-ink">Clearance</span>
      <Select
        aria-label="Clearance"
        value={value ?? ''}
        disabled={!clearances.length}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">None · grant a resource</option>
        {clearances.map((c) => (
          <option key={c.code} value={c.code}>
            {c.code}
          </option>
        ))}
      </Select>
      {chosen && <span className="text-caption text-muted-foreground">{chosen.description}</span>}
    </label>
  );
}
