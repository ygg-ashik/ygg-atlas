// src/ui/catalog-combobox.tsx
import * as React from 'react';
import { Command } from 'cmdk';
import { FIELD_CLASS, FIELD_MONO_CLASS } from './field-styles';
import { cn } from './utils';

export interface CatalogOption {
  /** The catalog path, e.g. `demo/order/revenue` or `demo/order/*`. */
  value: string;
  label: string;
  kind: 'source' | 'entity' | 'metric';
}

export interface CatalogComboboxProps {
  options: readonly CatalogOption[];
  /** The chosen path ('' when none). */
  value: string;
  onValueChange: (path: string) => void;
  /** Accessible name of the input. */
  label: string;
  placeholder?: string;
  emptyText?: string;
  className?: string;
}

const ITEM =
  'flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] text-body data-[selected=true]:bg-primary/10 data-[selected=true]:text-ink';

/** Inline catalog picker (DESIGN.md › catalog-combobox): a mono field with a cmdk
 * list in a glass popover. Only listed catalog paths can be chosen. */
export function CatalogCombobox({
  options,
  value,
  onValueChange,
  label,
  placeholder = 'Search the catalog: metric, entity or source',
  emptyText = 'No catalog path matches',
  className,
}: CatalogComboboxProps) {
  const [query, setQuery] = React.useState(value);
  const [synced, setSynced] = React.useState(value);
  // A new value from the parent (e.g. a reset) replaces whatever was typed.
  if (synced !== value) {
    setSynced(value);
    setQuery(value);
  }
  const [open, setOpen] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // cmdk always renders aria-expanded="true"; keep the real state on the input.
  React.useEffect(() => {
    inputRef.current?.setAttribute('aria-expanded', String(open));
  });

  const choose = (path: string) => {
    onValueChange(path);
    setQuery(path);
    setOpen(false);
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape' && open) {
      e.preventDefault();
      setOpen(false);
    }
  };
  return (
    <Command label={label} onKeyDown={onKeyDown} className={cn('relative', className)}>
      <Command.Input
        ref={inputRef}
        value={query}
        onValueChange={(q) => {
          setQuery(q);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          // Leaving the field abandons an unfinished search: show the chosen path again.
          setOpen(false);
          setQuery(value);
        }}
        placeholder={placeholder}
        className={cn(FIELD_CLASS, FIELD_MONO_CLASS)}
      />
      {open && (
        <Command.List
          onMouseDown={(e) => e.preventDefault()}
          className="glass absolute inset-x-0 top-[calc(100%+6px)] z-20 max-h-72 origin-top overflow-y-auto rounded-shell p-2 animate-materialize-in"
        >
          <Command.Empty className="px-2.5 py-2 text-[13.5px] text-muted-foreground">
            {emptyText}
          </Command.Empty>
          {options.map((o) => (
            <Command.Item
              key={o.value}
              value={o.value}
              keywords={[o.label]}
              onSelect={() => choose(o.value)}
              className={ITEM}
            >
              <span className="w-[46px] shrink-0 text-[11px] text-muted-foreground">{o.kind}</span>
              <span className="min-w-0 truncate">{o.label}</span>
              <span className="ml-auto font-mono text-[11px] text-muted-foreground">{o.value}</span>
            </Command.Item>
          ))}
        </Command.List>
      )}
    </Command>
  );
}
