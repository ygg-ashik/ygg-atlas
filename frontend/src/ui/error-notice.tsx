// src/ui/error-notice.tsx
import type * as React from 'react';
import { Button } from './button';
import { Morph } from './morph';
import { Notice } from './notice';

export interface ErrorNoticeProps {
  /** "Couldn't load users". */
  title: React.ReactNode;
  /** The fact and what it means ("The access service didn't answer (503). Nothing changed."). */
  children?: React.ReactNode;
  onRetry: () => void;
  /** While the retry is in flight the pill morphs to "Loading…". */
  retrying?: boolean;
  className?: string;
}

/** A load failure stated as fact with a Retry (DESIGN.md › notice-error). */
export function ErrorNotice({
  title,
  children,
  onRetry,
  retrying = false,
  className,
}: ErrorNoticeProps) {
  return (
    <Notice
      role="alert"
      icon="!"
      title={title}
      className={className}
      action={
        <Button
          variant="pill"
          size="sm"
          onClick={onRetry}
          disabled={retrying}
          aria-label={retrying ? 'Loading' : 'Retry'}
        >
          <Morph done={retrying} from="↻ Retry" to="Loading…" />
        </Button>
      }
    >
      {children}
    </Notice>
  );
}
