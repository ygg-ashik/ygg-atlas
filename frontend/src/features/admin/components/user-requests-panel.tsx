import { Inbox } from 'lucide-react';
import { Link } from 'react-router-dom';
import { type AccessRequest } from '@/api/access-requests';
import { type UserDetail } from '@/api/admin-users';
import { useRequestQueue } from '@/api/hooks/use-access-requests';
import { describeMutationError } from '@/api/mutation-errors';
import {
  Button,
  EmptyState,
  ErrorNotice,
  Notice,
  SkeletonRegion,
  SkeletonRows,
  StatusPill,
  Tag,
} from '@/ui';
import { seenAt } from '../format';
import { requestTargetText } from '../request-lines';
import { REQUEST_TONE } from './request-queue-row';
import { INSET_LIST } from './surfaces';

const QUEUE_LINK = 'text-primary-text underline-offset-4 hover:underline';

function RequestLine({ request }: { request: AccessRequest }) {
  return (
    <li
      aria-label={`${request.kind} · ${request.target_label}`}
      className="flex min-h-[52px] items-center gap-3 border-b border-border/50 px-4 py-2.5 last:border-b-0"
    >
      <Tag>{request.kind}</Tag>
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-[13px] text-ink">{requestTargetText(request)}</div>
        <div className="truncate text-[12.5px] text-muted-foreground">
          {request.note && <>“{request.note}” · </>}
          <span className="tabular-nums">{seenAt(request.created_at)}</span>
        </div>
      </div>
      <StatusPill tone={REQUEST_TONE[request.status]} diamond={request.status === 'declined'}>
        {request.status}
      </StatusPill>
    </li>
  );
}

/** The user's requests, every status, newest first: `GET /admin/requests?user_id=`.
 * The backend keeps it inside the viewer's decide scope (a manager sees only
 * group requests for their subtree); a 403 says so. Decisions happen in the queue. */
export function UserRequestsPanel({ user }: { user: UserDetail }) {
  const requests = useRequestQueue('all', { userId: user.id });
  if (requests.isPending) {
    return (
      <SkeletonRegion label="requests" className="rounded-lg bg-card">
        <SkeletonRows count={3} />
      </SkeletonRegion>
    );
  }
  if (requests.isError && !requests.data) {
    const info = describeMutationError(requests.error);
    if (info.kind === 'forbidden') {
      return (
        <Notice icon="·" title="Not in your queue">
          {info.message} Requests show here for people whose requests you may decide.
        </Notice>
      );
    }
    return (
      <ErrorNotice
        title="Couldn't load requests"
        onRetry={() => void requests.refetch()}
        retrying={requests.isFetching}
      />
    );
  }
  if (!requests.items.length) {
    return (
      <EmptyState icon={<Inbox className="h-5 w-5" />} title="No requests">
        This user hasn&apos;t asked for anything you decide.
      </EmptyState>
    );
  }
  return (
    <div>
      <p className="mb-2.5 text-caption text-muted-foreground">
        Requests you may decide, newest first. Decide them in{' '}
        <Link to="/admin/requests" className={QUEUE_LINK}>
          Access requests
        </Link>
        .
      </p>
      <ul aria-label={`Requests from ${user.display_name || user.email}`} className={INSET_LIST}>
        {requests.items.map((r) => (
          <RequestLine key={r.id} request={r} />
        ))}
      </ul>
      {requests.hasNextPage && (
        <div className="mt-3.5 flex justify-center">
          <Button
            variant="pill"
            onClick={() => void requests.fetchNextPage()}
            disabled={requests.isFetchingNextPage}
          >
            {requests.isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}
    </div>
  );
}
