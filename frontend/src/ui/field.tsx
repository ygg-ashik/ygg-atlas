// src/ui/field.tsx
import * as React from 'react';
import { cn } from './utils';

type ControlProps = {
  id?: string;
  'aria-describedby'?: string;
  'aria-invalid'?: boolean | 'true' | 'false';
};

export interface FieldProps {
  label: React.ReactNode;
  /** A single form control; it receives the id, aria-describedby and aria-invalid. */
  children: React.ReactElement<ControlProps>;
  hint?: React.ReactNode;
  /** Inline error: says what to do. Marks the control invalid. */
  error?: React.ReactNode;
  className?: string;
}

/** Inline validation message under a field (DESIGN.md › field-error). */
export function FieldError({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    <p id={id} className="flex items-center gap-1.5 text-[12.5px] text-negative">
      <span
        aria-hidden
        className="grid h-[15px] w-[15px] shrink-0 place-items-center rounded-full bg-negative text-[10px] font-bold text-card"
      >
        !
      </span>
      {children}
    </p>
  );
}

/** Label + control + hint + inline error, wired for assistive tech. */
export function Field({ label, children, hint, error, className }: FieldProps) {
  const autoId = React.useId();
  const id = children.props.id ?? autoId;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [children.props['aria-describedby'], hintId, errorId]
    .filter(Boolean)
    .join(' ');
  const control = React.cloneElement(children, {
    id,
    'aria-describedby': describedBy || undefined,
    ...(error ? { 'aria-invalid': true } : {}),
  });
  return (
    <div className={cn('grid gap-1.5', className)}>
      <label htmlFor={id} className="text-label font-medium text-ink">
        {label}
      </label>
      {control}
      {hint && (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && <FieldError id={errorId}>{error}</FieldError>}
    </div>
  );
}
