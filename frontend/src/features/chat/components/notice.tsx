import { AlertCircle, Clock3, ShieldAlert } from 'lucide-react';
import { Button, cn } from '@/ui';

interface NoticeProps {
  kind: 'blocked' | 'error' | 'stale';
  message: string;
  onRetry?: () => void;
}

const ICON = { blocked: ShieldAlert, error: AlertCircle, stale: Clock3 } as const;

/** DESIGN.md › notice-denied / notice-warning: state the fact plus a next step. Never hide it. */
export function Notice({ kind, message, onRetry }: NoticeProps) {
  const Icon = ICON[kind];
  const stale = kind === 'stale';
  return (
    <div
      role="status"
      className={cn(
        'my-3 flex items-start gap-3 rounded-card px-4 py-3.5',
        stale
          ? 'bg-warning/10 shadow-[0_0_0_1px_hsl(var(--warning)/0.25)]'
          : 'bg-card shadow-[0_0_0_1px_hsl(var(--border))]',
      )}
    >
      <span
        className={cn(
          'grid h-[30px] w-[30px] shrink-0 place-items-center rounded-full',
          stale ? 'bg-warning/20 text-warning' : 'bg-foreground/5 text-ink',
        )}
      >
        <Icon aria-hidden className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1 text-sm text-body">
        <p className="font-medium text-ink">{message}</p>
        {stale && <p>Recent changes may be missing from these numbers.</p>}
      </div>
      {kind === 'error' && onRetry && (
        <Button variant="pill" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}
