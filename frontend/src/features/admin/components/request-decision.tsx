// Deciding one access request: approve through a review card showing the exact
// change (with an expiry for resource grants), or decline with an optional note.
// A 409 is settled against the refetched queue: if the request is no longer
// pending someone else decided it (final, no Retry); if it still is, the 409 is
// the stale-actor case and the review offers Retry.
import { useRef, useState } from 'react';
import { type AccessRequest, type RequestDecision } from '@/api/access-requests';
import { useCapabilityCatalog } from '@/api/hooks/use-capability-catalog';
import { useApproveRequest, useDeclineRequest } from '@/api/hooks/use-access-requests';
import { describeMutationError } from '@/api/mutation-errors';
import { Button, DateField, Field, FieldError, isIsoDate, ReviewCard, Textarea } from '@/ui';
import { expiryToIso, plusDays, todayUtc } from '../grant-rules';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { APPROVE_AUDIT, approveLines } from '../request-lines';

/** A queue row: the request as last known, plus a notice when it was decided elsewhere. */
export interface QueueRow {
  request: AccessRequest;
  notice?: string;
}

export interface DecisionHandlers {
  /** Record the outcome so the row keeps showing it after the queue refetches. */
  onSettled: (row: QueueRow) => void;
  /** Refetch the pending queue; true when `requestId` is still pending there. */
  stillPending: (requestId: string) => Promise<boolean>;
}

const DEFAULT_DAYS = 90;
const defaultExpiry = () => plusDays(todayUtc(), DEFAULT_DAYS);
const firstName = (request: AccessRequest) =>
  request.requester?.display_name.split(' ')[0] || 'the requester';

/** Why a resource approval's expiry can't be sent, or null. '' means no expiry;
 * a date must be after today in UTC (the backend refuses a past expiry). */
export function approvalExpiryError(expiry: string, today: string = todayUtc()): string | null {
  if (expiry === '') return null;
  if (!isIsoDate(expiry)) return 'Enter a date as YYYY-MM-DD (UTC), or clear it for no expiry.';
  if (expiry <= today) return 'Pick a date after today (UTC), or clear it for no expiry.';
  return null;
}

/** The approval body. Resource: always an explicit expiry, a date or null (no
 * expiry), never absent (absent would mean the backend's default). Others: empty. */
function approvalBody(request: AccessRequest, expiry: string): RequestDecision {
  return request.kind === 'resource' ? { expires_at: expiryToIso(expiry) } : {};
}

/** The decided request, keeping the requester as shown when it was pending. */
const decided = (before: AccessRequest, after: AccessRequest): AccessRequest => ({
  ...after,
  requester: before.requester ?? after.requester,
});

/** True when the 409 means someone else decided it; the row then shows the
 * backend's sentence and no actions. */
async function settledElsewhere(
  error: unknown,
  request: AccessRequest,
  { onSettled, stillPending }: DecisionHandlers,
): Promise<boolean> {
  const info = describeMutationError(error);
  if (info.kind !== 'conflict' || (await stillPending(request.id))) return false;
  onSettled({ request, notice: info.message });
  return true;
}

/** The approval review of one request: opened by `start`, rendered by `ApproveReview`. */
export function useApproval(request: AccessRequest, handlers: DecisionHandlers) {
  const write = useReviewedWrite();
  const approve = useApproveRequest();
  const [expiry, setExpiry] = useState(defaultExpiry);
  const [showInvalid, setShowInvalid] = useState(false);
  const expiryRef = useRef(expiry);
  expiryRef.current = expiry;
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  const start = () => {
    const initial = defaultExpiry();
    setExpiry(initial);
    setShowInvalid(false);
    write.open({
      slot: request.id,
      title: `Approve request from ${request.requester?.display_name ?? 'requester'}`,
      auditAction: APPROVE_AUDIT[request.kind],
      lines: approveLines(request, { expiry: initial, roles: [] }),
      applyLabel: 'Approve',
      appliedLabel: 'Approved',
      run: async () => {
        try {
          const decision = approvalBody(request, expiryRef.current);
          const out = await approve.mutateAsync({ requestId: request.id, decision });
          handlersRef.current.onSettled({ request: decided(request, out) });
        } catch (error) {
          if (!(await settledElsewhere(error, request, handlersRef.current))) throw error;
          write.dismiss();
        }
      },
    });
  };

  const expiryError = request.kind === 'resource' ? approvalExpiryError(expiry) : null;
  const apply = () => {
    if (expiryError) {
      setShowInvalid(true);
      return;
    }
    void write.apply();
  };

  return {
    write,
    start,
    expiry,
    setExpiry,
    expiryError: showInvalid ? expiryError : null,
    apply,
  };
}

type Approval = ReturnType<typeof useApproval>;

/** The review card of an open approval; the diff follows the expiry as it is edited. */
export function ApproveReview({
  request,
  approval,
}: {
  request: AccessRequest;
  approval: Approval;
}) {
  const catalog = useCapabilityCatalog();
  const { review } = approval.write;
  if (!review) return null;
  const lines = approveLines(request, {
    expiry: approval.expiry,
    roles: catalog.data?.roles ?? [],
  });
  const editable = review.status === 'open' || review.status === 'conflict';
  return (
    <ReviewCard
      title={review.spec.title}
      lines={lines}
      status={review.status}
      auditAction={review.spec.auditAction}
      applyLabel={review.spec.applyLabel}
      appliedLabel={review.spec.appliedLabel}
      onApply={approval.apply}
      onDismiss={approval.write.dismiss}
    >
      {request.kind === 'resource' && (
        <div className="mb-2.5 flex flex-wrap items-end gap-2">
          <Field
            label="Expiry"
            hint="Prefilled at 90 days; resource grants should expire. Clear it for no expiry."
            error={approval.expiryError ?? undefined}
          >
            <DateField
              value={approval.expiry}
              disabled={!editable}
              onChange={(e) => approval.setExpiry(e.target.value)}
            />
          </Field>
          <div className="mb-[22px] flex gap-1.5">
            <Button
              variant="pill"
              size="sm"
              disabled={!editable}
              onClick={() => approval.setExpiry(defaultExpiry())}
            >
              90 days
            </Button>
            <Button
              variant="pill"
              size="sm"
              disabled={!editable}
              onClick={() => approval.setExpiry('')}
            >
              No expiry
            </Button>
          </div>
        </div>
      )}
      {review.error && (
        <div role="alert" className="mb-2">
          <FieldError>{review.error}</FieldError>
        </div>
      )}
    </ReviewCard>
  );
}

interface DeclinePanelProps extends DecisionHandlers {
  request: AccessRequest;
  onClose: () => void;
}

/** Decline with an optional note to the requester. Declining changes no access. */
export function DeclinePanel({ request, onClose, onSettled, stillPending }: DeclinePanelProps) {
  const decline = useDeclineRequest();
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  // A 409 on a still-pending request is the stale-actor case: nothing was
  // written, and the button reads Retry, as on an approval's review card.
  const [conflict, setConflict] = useState(false);
  const submit = async () => {
    setError(null);
    const text = note.trim();
    try {
      const out = await decline.mutateAsync({
        requestId: request.id,
        decision: text ? { note: text } : {},
      });
      onSettled({ request: decided(request, out) });
    } catch (e) {
      if (await settledElsewhere(e, request, { onSettled, stillPending })) return;
      const info = describeMutationError(e);
      setConflict(info.kind === 'conflict');
      setError(info.message);
    }
  };
  return (
    <section
      aria-label="Decline request"
      className="mt-3 rounded-card bg-card px-4 py-3.5 shadow-[0_0_0_1px_hsl(var(--border)),0_6px_20px_hsl(var(--ink)/0.06)]"
    >
      <p className="mb-2 flex items-center gap-2 text-label text-muted-foreground">
        <span aria-hidden>◇</span>
        <b className="font-medium text-ink">Decline request</b>· changes no access
      </p>
      <Field
        label={
          <>
            Note to {firstName(request)}{' '}
            <span className="font-normal text-muted-foreground">optional</span>
          </>
        }
      >
        <Textarea
          value={note}
          maxLength={500}
          className="min-h-[64px]"
          placeholder="e.g. Paid search moved to the agency; no access needed."
          onChange={(e) => setNote(e.target.value)}
        />
      </Field>
      {error && (
        <div role="alert" className="mt-2">
          <FieldError>{error}</FieldError>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={() => void submit()} disabled={decline.isPending}>
          {conflict ? 'Retry' : 'Decline request'}
        </Button>
        <Button variant="pill" onClick={onClose} disabled={decline.isPending}>
          Keep pending
        </Button>
      </div>
    </section>
  );
}
