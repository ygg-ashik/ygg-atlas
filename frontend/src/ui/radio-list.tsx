// src/ui/radio-list.tsx
import * as React from 'react';
import { moveIndex } from './roving';
import { cn } from './utils';

export interface RadioListOption<V extends string> {
  value: V;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** A further line under the description (e.g. "Decided by Sara Mansour"). */
  detail?: React.ReactNode;
  /** Right-aligned meta (e.g. a mono grant count). */
  meta?: React.ReactNode;
  disabled?: boolean;
}

export interface RadioListProps<V extends string> {
  options: readonly RadioListOption<V>[];
  value: V | null;
  onChange: (value: V) => void;
  /** Accessible name of the group. */
  label: string;
  className?: string;
}

function tabStop<V extends string>(options: readonly RadioListOption<V>[], value: V | null) {
  const selected = options.findIndex((o) => o.value === value && !o.disabled);
  return selected >= 0 ? selected : options.findIndex((o) => !o.disabled);
}

/** Selectable inset rows with a radio (DESIGN.md › radio-row). */
export function RadioList<V extends string>({
  options,
  value,
  onChange,
  label,
  className,
}: RadioListProps<V>) {
  const refs = React.useRef<(HTMLDivElement | null)[]>([]);
  const stop = tabStop(options, value);
  const pick = (i: number) => {
    const option = options[i];
    if (option && !option.disabled) onChange(option.value);
  };
  const onKeyDown = (e: React.KeyboardEvent, i: number) => {
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      pick(i);
      return;
    }
    const next = moveIndex(
      e.key,
      i,
      options.map((o) => !o.disabled),
    );
    if (next === null) return;
    e.preventDefault();
    refs.current[next]?.focus();
    pick(next);
  };
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        'overflow-hidden rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.5)]',
        className,
      )}
    >
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <div
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            role="radio"
            aria-checked={on}
            aria-disabled={o.disabled || undefined}
            tabIndex={i === stop ? 0 : -1}
            onClick={() => pick(i)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              'flex min-h-[52px] items-center gap-3 border-b border-border/50 px-4 py-3 outline-none transition-colors duration-200 last:border-b-0 focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-primary/15',
              o.disabled
                ? 'cursor-default opacity-55'
                : 'cursor-pointer hover:bg-foreground/[0.03]',
              on && 'bg-primary/10 hover:bg-primary/10',
            )}
          >
            <span
              aria-hidden
              className={cn(
                'grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border-[1.5px] transition-colors',
                on ? 'border-primary' : 'border-border',
              )}
            >
              {on && <span className="h-2 w-2 rounded-full bg-primary" />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-[14.5px] font-medium text-ink">
                {o.title}
              </div>
              {o.description && (
                <div className="mt-px text-[12.5px] text-muted-foreground">{o.description}</div>
              )}
              {o.detail && <div className="mt-1 text-[12.5px] text-body">{o.detail}</div>}
            </div>
            {o.meta}
          </div>
        );
      })}
    </div>
  );
}
