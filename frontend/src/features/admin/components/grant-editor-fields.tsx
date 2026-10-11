// Field groups of the grant editor (effect, expiry, deny confirmation).
import { Button, Checkbox, DateField, Field, Notice, SegmentedControl, StatusPill } from '@/ui';
import { type GrantEffectChoice } from '../grant-rules';

export function EffectField({
  value,
  onChange,
}: {
  value: GrantEffectChoice;
  onChange: (effect: GrantEffectChoice) => void;
}) {
  return (
    <div className="grid gap-1.5">
      <span className="text-label font-medium text-ink">Effect</span>
      <SegmentedControl<GrantEffectChoice>
        kind="radio"
        label="Effect"
        value={value}
        onChange={onChange}
        options={[
          { value: 'allow', label: <StatusPill tone="positive">Allow</StatusPill> },
          {
            value: 'deny',
            label: (
              <StatusPill tone="negative" diamond>
                Deny
              </StatusPill>
            ),
          },
        ]}
      />
    </div>
  );
}

interface ExpiryFieldProps {
  value: string;
  onChange: (date: string) => void;
  /** The +90 days preset (YYYY-MM-DD). */
  preset: string;
  error?: string;
}

export function ExpiryField({ value, onChange, preset, error }: ExpiryFieldProps) {
  return (
    <div className="grid gap-1.5">
      <Field label="Expiry" hint="UTC date; empty means never" error={error}>
        <DateField value={value} onChange={(e) => onChange(e.target.value)} />
      </Field>
      <div className="flex gap-1.5">
        <Button
          type="button"
          variant="pill"
          size="sm"
          data-selected={value === preset}
          onClick={() => onChange(preset)}
        >
          90 days
        </Button>
        <Button
          type="button"
          variant="pill"
          size="sm"
          data-selected={value === ''}
          onClick={() => onChange('')}
        >
          Never
        </Button>
      </div>
    </div>
  );
}

interface DenyConfirmProps {
  /** Who loses access, e.g. "Everyone in marketing and its subgroups". */
  who: string;
  target: string;
  count?: number;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export function DenyConfirm({ who, target, count, checked, onChange }: DenyConfirmProps) {
  const label =
    count === undefined
      ? 'I understand this restricts access'
      : `I understand this restricts ${count} members`;
  return (
    <Notice tone="warning" icon="!" title="A deny wins over every allow" className="mt-3.5">
      {who} loses <span className="font-mono">{target || 'this target'}</span>, even where another
      grant allows it.
      <div className="mt-2.5">
        <Checkbox label={label} checked={checked} onChange={(e) => onChange(e.target.checked)} />
      </div>
    </Notice>
  );
}
