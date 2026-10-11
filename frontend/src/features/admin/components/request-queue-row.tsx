import { useState } from 'react';
import { type AccessRequest, type RequestStatus } from '@/api/access-requests';
import { Avatar, Button, StatusPill, Tag, type StatusTone } from '@/ui';
import { seenAt } from '../format';
import { requestTargetText } from '../request-lines';
import {
  ApproveReview,
  DeclinePanel,
  useApproval,
  type DecisionHandlers,
  type QueueRow,
} from './request-decision';
import { CARD } from './surfaces';

/** A request status as a pill tone (the queue and the user's Requests tab). */
export const REQUEST_TONE: Record<RequestStatus, StatusTone> = {
  pending: 'warning',
  approved: 'positive',
  declined: 'negative',
  cancelled: 'muted',
};

interface RequestQueueRowProps extends DecisionHandlers {
  row: QueueRow;
  /** The viewer's user id; null while their access loads (no actions: fail closed). */
  viewerId: string | null;
  /** Copy only: who decides the viewer's own requests. */
  viewerIsAdmin: boolean;
}

/** One request in the queue (screen 10): requester, kind, mono target, note,
 * times, status, and, for someone else's pending request, Approve / Decline. */
export function RequestQueueRow({
  row,
  viewerId,
  viewerIsAdmin,
  onSettled,
  stillPending,
}: RequestQueueRowProps) {
  const { request } = row;
  const [declining, setDeclining] = useState(false);
  const approval = useApproval(request, { onSettled, stillPending });
  const name = requesterName(request);
  const busy = declining || approval.write.review !== null;
  const { own, pending, canAct } = rowState(row, viewerId, busy);
  return (
    <article
      aria-label={`${name} · ${request.kind} · ${request.target_label}`}
      className={`${CARD} px-[18px] py-4`}
    >
      <div className="flex items-start gap-3">
        <Avatar name={name} />
        <RequestSummary row={row} own={own} />
        <div className="grid justify-items-end gap-2">
          <RowStatus row={row} />
          {canAct && <RowActions onDecline={() => setDeclining(true)} onApprove={approval.start} />}
          {pending && own && <OwnRequestNote kind={request.kind} viewerIsAdmin={viewerIsAdmin} />}
        </div>
      </div>
      <ApproveReview request={request} approval={approval} />
      {declining && pending && (
        <DeclinePanel
          request={request}
          onClose={() => setDeclining(false)}
          onSettled={onSettled}
          stillPending={stillPending}
        />
      )}
    </article>
  );
}

/** Actions only once the viewer is known and the request is someone else's (fail closed). */
function rowState({ request, notice }: QueueRow, viewerId: string | null, busy: boolean) {
  const own = !!request.requester && request.requester.user_id === viewerId;
  const pending = request.status === 'pending' && !notice;
  const canAct = pending && viewerId !== null && !!request.requester && !own && !busy;
  return { own, pending, canAct };
}

function RowActions({ onDecline, onApprove }: { onDecline: () => void; onApprove: () => void }) {
  return (
    <div className="flex gap-1.5">
      <Button variant="pill" size="sm" onClick={onDecline}>
        Decline
      </Button>
      <Button size="sm" onClick={onApprove}>
        Approve
      </Button>
    </div>
  );
}

/** Nobody decides their own request; say who does instead. */
function OwnRequestNote({
  kind,
  viewerIsAdmin,
}: {
  kind: AccessRequest['kind'];
  viewerIsAdmin: boolean;
}) {
  return (
    <span className="max-w-[200px] text-right text-caption text-muted-foreground">
      {viewerIsAdmin || kind !== 'group'
        ? 'Another admin decides your own requests'
        : "An admin decides: managers can't change their own membership"}
    </span>
  );
}

const requesterName = (request: AccessRequest) =>
  request.requester?.display_name || request.requester?.email || 'Unknown requester';

function RequestSummary({ row, own }: { row: QueueRow; own: boolean }) {
  const { request, notice } = row;
  return (
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-2">
        <b className="font-medium text-ink">{requesterName(request)}</b>
        {request.requester?.email && (
          <span className="text-caption text-muted-foreground">{request.requester.email}</span>
        )}
        {own && <Tag>your request</Tag>}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <Tag>{request.kind}</Tag>
        <span className="font-mono text-[13px] text-ink">{requestTargetText(request)}</span>
        <span className="text-caption tabular-nums text-muted-foreground">
          {seenAt(request.created_at)}
        </span>
      </div>
      {request.note && <p className="mt-2 text-sm text-body">“{request.note}”</p>}
      {request.status !== 'pending' && <DecisionLine row={row} />}
      {notice && <p className="mt-2 text-[12.5px] text-body">{notice}</p>}
    </div>
  );
}

/** Decided elsewhere (a 409 and gone from the queue): the outcome is not ours to show. */
function RowStatus({ row }: { row: QueueRow }) {
  if (row.notice) return <StatusPill tone="muted">decided</StatusPill>;
  const { status } = row.request;
  return (
    <StatusPill tone={REQUEST_TONE[status]} diamond={status === 'declined'}>
      {status}
    </StatusPill>
  );
}

function DecisionLine({ row }: { row: QueueRow }) {
  const { decided_by: by, decided_at: at, decision_note: note } = row.request;
  const parts = [by?.display_name, at ? seenAt(at) : null, note ? `“${note}”` : null].filter(
    Boolean,
  );
  if (!parts.length) return null;
  return <p className="mt-2 text-caption text-body">{parts.join(' · ')}</p>;
}
