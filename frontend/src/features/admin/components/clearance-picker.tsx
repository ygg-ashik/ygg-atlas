import { useCapabilityCatalog } from '@/api/hooks/use-capability-catalog';
import { FutureControl, Select, Tag } from '@/ui';

interface ClearancePickerProps {
  /** The chosen clearance code, or null for a resource grant. */
  value: string | null;
  onChange: (code: string | null) => void;
}

/** Phase-3 field clearances. Until `/meta/capabilities` lists `clearances`,
 * shown disabled ("Arrives with row and field controls"). */
export function ClearancePicker({ value, onChange }: ClearancePickerProps) {
  const clearances = useCapabilityCatalog().data?.clearances;
  if (!clearances) {
    return (
      <FutureControl label="Clearance">
        <Tag mono>fields:business_names</Tag>
        <Tag mono>fields:people_names</Tag>
      </FutureControl>
    );
  }
  return (
    <label className="grid gap-1.5 rounded-md border border-border px-3.5 py-3">
      <span className="text-label font-medium text-ink">Clearance</span>
      <Select
        aria-label="Clearance"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">None · grant a resource</option>
        {clearances.map((c) => (
          <option key={c.code} value={c.code}>
            {c.code}
          </option>
        ))}
      </Select>
    </label>
  );
}
