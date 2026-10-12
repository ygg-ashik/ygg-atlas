import type * as React from 'react';

/** An `inset-list` of settings rows on a solid card (DESIGN.md › settings-row). */
export function SettingsGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      role="group"
      aria-label={label}
      className="overflow-hidden rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.5)] [&>*+*]:border-t [&>*+*]:border-border/50"
    >
      {children}
    </div>
  );
}

interface SettingsRowProps {
  title: React.ReactNode;
  hint?: React.ReactNode;
  /** The control on the right: a segmented control, a button, key caps. */
  children: React.ReactNode;
}

/** Title and a muted line on the left, the control on the right; wraps when narrow. */
export function SettingsRow({ title, hint, children }: SettingsRowProps) {
  return (
    <div className="flex min-h-[60px] flex-wrap items-center gap-3.5 px-4 py-3.5">
      <div className="min-w-[200px] flex-1">
        <div className="text-[14.5px] font-medium text-ink">{title}</div>
        {hint && <div className="mt-px text-[12.5px] text-muted-foreground">{hint}</div>}
      </div>
      {children}
    </div>
  );
}
