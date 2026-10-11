// src/ui/review-card.tsx
import type * as React from 'react';
import { Button } from './button';
import { DiffBlock, type DiffLine } from './diff-block';
import { Morph } from './morph';

/** open: awaiting approval · applying: request in flight · applied: done ·
 * conflict: access changed while it ran (409), nothing was written. */
export type ReviewStatus = 'open' | 'applying' | 'applied' | 'conflict';

export interface ReviewCardProps {
  lines: readonly DiffLine[];
  status: ReviewStatus;
  /** The audit action this write records, e.g. `grant.create`. */
  auditAction: string;
  onApply: () => void;
  onDismiss?: () => void;
  title?: string;
  applyLabel?: string;
  appliedLabel?: string;
  /** Extra inputs shown above the diff (e.g. an expiry field). */
  children?: React.ReactNode;
}

const CONFLICT =
  'Access changed while this request was running; nothing was written. Retry to apply against the current access.';

/** Review before apply (DESIGN.md › review-card): every widening or destructive
 * write shows its diff first; Apply morphs in place to its done label. */
export function ReviewCard({
  lines,
  status,
  auditAction,
  onApply,
  onDismiss,
  title = 'Proposed change',
  applyLabel = 'Apply',
  appliedLabel = 'Applied',
  children,
}: ReviewCardProps) {
  const applied = status === 'applied';
  const audit = <span className="font-mono text-xs">{auditAction}</span>;
  return (
    <section
      aria-label={title}
      data-status={status}
      className="my-2.5 rounded-card bg-card px-4 py-3.5 shadow-[0_0_0_1px_hsl(var(--border)),0_6px_20px_rgba(0,0,0,0.06)]"
    >
      <p className="mb-2 flex items-center gap-2 text-label text-muted-foreground">
        <span aria-hidden>◇</span>
        <b className="font-medium text-ink">{title}</b>·{' '}
        {applied ? 'applied' : 'needs your approval'}
      </p>
      {children}
      <DiffBlock lines={lines} />
      {status === 'conflict' && (
        <p role="alert" className="mt-2.5 text-[12.5px] text-negative">
          {CONFLICT}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          onClick={onApply}
          disabled={applied || status === 'applying'}
          aria-busy={status === 'applying'}
        >
          <Morph
            done={applied}
            from={status === 'conflict' ? 'Retry' : applyLabel}
            to={`✓ ${appliedLabel}`}
          />
        </Button>
        {!applied && onDismiss && (
          <Button variant="pill" onClick={onDismiss}>
            Dismiss
          </Button>
        )}
        <span className="ml-auto text-caption text-muted-foreground">
          Recorded as {audit}
          {applied && ' in the audit log'}
        </span>
      </div>
    </section>
  );
}
