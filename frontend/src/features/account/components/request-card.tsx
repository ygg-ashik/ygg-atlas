import { useState } from 'react';
import { type AccessRequest, type RequestStatus } from '@/api/access-requests';
import { useCancelRequest } from '@/api/hooks/use-access-requests';
import { describeMutationError } from '@/api/mutation-errors';
import { formatDateTime } from '@/lib/utils';
import {
  actionToast,
  Button,
  ReviewCard,
  StatusPill,
  Tag,
  type ReviewStatus,
  type StatusTone,
} from '@/ui';

const TONE: Record<RequestStatus, StatusTone> = {
  pending: 'warning',
  approved: 'positive',
  declined: 'negative',
  cancelled: 'muted',
};

const WAITING_ON: Record<AccessRequest['kind'], string> = {
  group: "Waiting on the group's managers",
  role: 'Waiting on an admin',
  resource: 'Waiting on an admin',
};

interface RequestCardProps {
  request: AccessRequest;
  /** Reload the list (after a 409: the request was decided meanwhile). */
  onReload: () => void;
}

/** One of the caller's requests (screen 3): kind, target, status pill, note,
 * the decision, and for a pending one a confirmed cancel. */
export function RequestCard({ request, onReload }: RequestCardProps) {
  const pending = request.status === 'pending';
  const titleId = `request-${request.id}`;
  return (
    <article
      aria-labelledby={titleId}
      className="rounded-card bg-card px-[18px] py-4 shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_2px_rgba(0,0,0,0.04)]"
    >
      <div className="flex items-start gap-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Tag>{request.kind}</Tag>
            <span id={titleId} className="font-mono text-[13px] text-ink">
              {request.target_label}
            </span>
          </div>
          <div className="mt-1 text-caption tabular-nums text-muted-foreground">
            Sent {formatDateTime(request.created_at)}
          </div>
        </div>
        <StatusPill tone={TONE[request.status]} diamond={request.status === 'declined'}>
          {request.status}
        </StatusPill>
      </div>
      <p className="mt-2.5 text-sm text-body">“{request.note}”</p>
      {!pending && <Decision request={request} />}
      {pending && <CancelControl request={request} onReload={onReload} />}
    </article>
  );
}

/** Never 'applied': that state says "in the audit log", and a cancel isn't
 * audited there. The card stays busy until the refreshed list replaces it. */
function reviewStatus(applying: boolean, applied: boolean): ReviewStatus {
  return applying || applied ? 'applying' : 'open';
}

function Decision({ request }: { request: AccessRequest }) {
  const who =
    request.status === 'cancelled' ? 'You cancelled it' : (request.decided_by?.display_name ?? '');
  if (!who && !request.decision_note) return null;
  return (
    <div className="mt-2.5 rounded-md bg-card-2 px-3 py-2.5 text-[13px] leading-normal text-body">
      {who && <b className="font-medium text-ink">{who}</b>}
      {who && request.decided_at && (
        <span className="text-caption tabular-nums text-muted-foreground">
          {' '}
          · {formatDateTime(request.decided_at)}
        </span>
      )}
      {request.decision_note && <div className="mt-0.5">{request.decision_note}</div>}
    </div>
  );
}

/** Cancel is destructive, so it is reviewed inline first. Cancelling changes no
 * access: it is recorded on the request row, not in `rbac_changes`. */
function CancelControl({ request, onReload }: RequestCardProps) {
  const [reviewing, setReviewing] = useState(false);
  const cancel = useCancelRequest();
  const apply = () =>
    cancel.mutate(request.id, {
      onError: (error) => {
        const info = describeMutationError(error);
        if (info.kind !== 'conflict') return;
        setReviewing(false);
        actionToast(info.message, { actionLabel: 'Reload', onAction: onReload });
      },
    });
  if (!reviewing) {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-2.5">
        <span className="text-caption text-muted-foreground">{WAITING_ON[request.kind]}</span>
        <span className="flex-1" />
        <Button variant="pill" size="sm" onClick={() => setReviewing(true)}>
          Cancel request
        </Button>
      </div>
    );
  }
  return (
    <ReviewCard
      title="Cancel this request"
      auditAction="access_requests.status"
      applyLabel="Cancel request"
      appliedLabel="Cancelled"
      status={reviewStatus(cancel.isPending, cancel.isSuccess)}
      onApply={apply}
      onDismiss={() => setReviewing(false)}
      lines={[
        { kind: 'context', text: `request ${request.kind} ${request.target_label}` },
        { kind: 'remove', text: 'status pending' },
        { kind: 'add', text: 'status cancelled' },
      ]}
    >
      <p className="mb-2 text-[12.5px] text-muted-foreground">
        Cancelling changes no access. It is recorded on the request itself, not in the audit log.
      </p>
      {cancel.errorInfo && cancel.errorInfo.kind !== 'conflict' && (
        <p role="alert" className="mb-2 text-[12.5px] text-negative">
          {cancel.errorInfo.message}
        </p>
      )}
    </ReviewCard>
  );
}
