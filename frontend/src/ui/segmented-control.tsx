// src/ui/segmented-control.tsx
import * as React from 'react';
import { moveIndex } from './roving';
import { cn } from './utils';

export interface SegmentOption<V extends string> {
  value: V;
  label: React.ReactNode;
  /** Optional tabular count after the label (tabs). */
  count?: number;
  disabled?: boolean;
}

export interface SegmentedControlProps<V extends string> {
  options: readonly SegmentOption<V>[];
  value: V;
  onChange: (value: V) => void;
  /** Accessible name of the group. */
  label: string;
  /** tabs: a tablist over panels · radio: kind pills (Group · Role · Resource). */
  kind?: 'tabs' | 'radio';
  /** Tabs only: ids become `${idBase}-tab-${value}` / `${idBase}-panel-${value}`. */
  idBase?: string;
  className?: string;
}

/** Id of the panel a tab controls; give it to the panel element with role="tabpanel". */
export function tabPanelId(idBase: string, value: string): string {
  return `${idBase}-panel-${value}`;
}
/** Id of a tab, for the panel's aria-labelledby. */
export function tabId(idBase: string, value: string): string {
  return `${idBase}-tab-${value}`;
}

const SEGMENT =
  'inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-label font-medium text-muted-foreground transition-[background-color,color,transform] duration-200 ease-out active:scale-[.96] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15 disabled:cursor-not-allowed disabled:opacity-45';
const SELECTED =
  'bg-card text-ink shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_3px_rgba(0,0,0,0.08)]';

/** Recessed capsule of segments (DESIGN.md › segmented-control). Arrow keys
 * move and select; only the selected segment is in the tab order. */
export function SegmentedControl<V extends string>({
  options,
  value,
  onChange,
  label,
  kind = 'tabs',
  idBase,
  className,
}: SegmentedControlProps<V>) {
  const refs = React.useRef<(HTMLButtonElement | null)[]>([]);
  const tabs = kind === 'tabs';
  const onKeyDown = (e: React.KeyboardEvent, index: number) => {
    const next = moveIndex(
      e.key,
      index,
      options.map((o) => !o.disabled),
    );
    const option = next === null ? undefined : options[next];
    if (next === null || !option) return;
    e.preventDefault();
    refs.current[next]?.focus();
    onChange(option.value);
  };
  return (
    <div
      role={tabs ? 'tablist' : 'radiogroup'}
      aria-label={label}
      className={cn(
        'inline-flex flex-wrap gap-0.5 rounded-full bg-card-2 p-[3px] shadow-[inset_0_0_0_1px_hsl(var(--border)/0.5)]',
        className,
      )}
    >
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role={tabs ? 'tab' : 'radio'}
            id={tabs && idBase ? tabId(idBase, o.value) : undefined}
            aria-controls={tabs && idBase ? tabPanelId(idBase, o.value) : undefined}
            aria-selected={tabs ? on : undefined}
            aria-checked={tabs ? undefined : on}
            tabIndex={on ? 0 : -1}
            disabled={o.disabled}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(SEGMENT, on && SELECTED)}
          >
            {o.label}
            {o.count !== undefined && (
              <span className="text-[11px] tabular-nums text-muted-foreground">{o.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
