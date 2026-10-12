// ⌘K quick actions for admins and managers: one request's approval, or one
// token's revocation, as the same review card the pages use, in a dialog.
import { useCallback, useState } from 'react';
import { type AccessRequest } from '@/api/access-requests';
import { useRequestQueue } from '@/api/hooks/use-access-requests';
import { useRevokeAdminToken } from '@/api/hooks/use-tokens';
import { type Token } from '@/api/tokens';
import { Avatar, Dialog, DialogContent, DialogDescription, DialogTitle, toast } from '@/ui';
import { useReviewDialog } from '../hooks/use-review-dialog';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { tokenRevokeReview } from '../review-lines';
import { ApproveReview, stillPendingAfter, useApproval, type QueueRow } from './request-decision';
import { RequestSummary } from './request-queue-row';
import { ReviewSlot } from './review-slot';

interface QuickDialogProps<T> {
  /** What to act on; the dialog is open while it is set. */
  target: T | null;
  onClose: () => void;
}

const WIDE = 'w-[min(600px,calc(100%-40px))]';

/** The last target, kept through the dialog's exit so its content doesn't blank. */
function useLastTarget<T>(target: T | null): T | null {
  const [last, setLast] = useState(target);
  if (target !== null && target !== last) setLast(target);
  return last;
}

/** Approve one access request (DESIGN.md › Quick actions): the request, then its
 * review card with the exact change. Dismiss closes the dialog. */
export function ApproveRequestDialog({ target, onClose }: QuickDialogProps<AccessRequest>) {
  const shown = useLastTarget(target);
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={WIDE}>
        {shown && <ApproveBody key={shown.id} request={shown} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function ApproveBody({ request, onClose }: { request: AccessRequest; onClose: () => void }) {
  const { refetch } = useRequestQueue('pending');
  const stillPending = useCallback(
    (requestId: string) => stillPendingAfter(refetch, requestId),
    [refetch],
  );
  const onSettled = useCallback((row: QueueRow) => {
    if (row.notice) toast(row.notice);
  }, []);
  const approval = useApproval(request, { onSettled, stillPending });
  useReviewDialog(approval.write, approval.start, onClose);
  const name = request.requester?.display_name || request.requester?.email || 'requester';
  return (
    <>
      <div className="pr-8">
        <DialogTitle>Approve request</DialogTitle>
        <DialogDescription className="mt-1">
          Applies exactly the change below. Nothing else moves.
        </DialogDescription>
      </div>
      <div className="flex items-start gap-3">
        <Avatar name={name} />
        <RequestSummary row={{ request }} own={false} />
      </div>
      <ApproveReview request={request} approval={approval} />
    </>
  );
}

/** Revoke one token (admin:tokens): its review card in a dialog. */
export function RevokeTokenDialog({ target, onClose }: QuickDialogProps<Token>) {
  const shown = useLastTarget(target);
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={WIDE}>
        {shown && <RevokeBody key={shown.id} token={shown} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

const SLOT = 'quick';

function RevokeBody({ token, onClose }: { token: Token; onClose: () => void }) {
  const write = useReviewedWrite();
  const { mutateAsync } = useRevokeAdminToken();
  const { open } = write;
  const start = useCallback(
    () => open(tokenRevokeReview(token, SLOT, () => mutateAsync(token.id))),
    [open, mutateAsync, token],
  );
  useReviewDialog(write, start, onClose);
  return (
    <>
      <div className="pr-8">
        <DialogTitle>Revoke {token.prefix}…?</DialogTitle>
        <DialogDescription className="mt-1">
          {token.name} · <span className="font-mono">{token.user_id}</span>. Anything using it gets
          401 on its next call.
        </DialogDescription>
      </div>
      <ReviewSlot write={write} slot={SLOT} />
    </>
  );
}
