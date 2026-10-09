// src/ui/field-styles.ts
// One look for every text control (DESIGN.md › field-input): solid card, hairline
// border, clay focus ring, negative border when aria-invalid.
export const FIELD_CLASS =
  'w-full rounded-md border border-border bg-card px-3 py-[9px] text-sm text-ink outline-none transition-[border-color,box-shadow] duration-200 ease-out placeholder:text-muted-2 focus-visible:border-primary-text focus-visible:ring-4 focus-visible:ring-primary/15 disabled:cursor-not-allowed disabled:bg-card-2 disabled:opacity-55 aria-[invalid=true]:border-negative';

/** Mono variant for paths, ids, dates and tokens. */
export const FIELD_MONO_CLASS = 'font-mono text-[13px]';
