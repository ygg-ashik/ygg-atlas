import { Inbox } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useMyRequests } from '@/api/hooks/use-access-requests';
import { Button, EmptyState, ErrorNotice, SkeletonRegion, SkeletonRows } from '@/ui';
import { AccountPage } from './account-page';
import { RequestCard } from './request-card';

/** Screen 3 · My requests: everything the caller asked for, newest first. */
export function MyRequestsPage() {
  const requests = useMyRequests();
  const reload = () => void requests.refetch();
  return (
    <AccountPage
      title="My requests"
      sub="Everything you've asked for, and what was decided."
      action={
        <Button asChild>
          <Link to="/account/requests/new">＋ New request</Link>
        </Button>
      }
    >
      {requests.isPending && (
        <SkeletonRegion
          label="your requests"
          className="overflow-hidden rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.5)]"
        >
          <SkeletonRows count={3} />
        </SkeletonRegion>
      )}
      {requests.isError && (
        <ErrorNotice
          title="Couldn't load your requests"
          onRetry={reload}
          retrying={requests.isFetching}
        >
          The access service didn't answer. Nothing changed; your requests are as you left them.
        </ErrorNotice>
      )}
      {requests.data && requests.data.length === 0 && (
        <EmptyState
          icon={<Inbox className="h-5 w-5" />}
          title="Nothing requested yet"
          actions={
            <Button asChild>
              <Link to="/account/requests/new">Request access</Link>
            </Button>
          }
        >
          When you ask for a group, a role or a resource, it shows up here with its status and the
          decision note.
        </EmptyState>
      )}
      {requests.data && requests.data.length > 0 && (
        <div className="grid gap-3">
          {requests.data.map((r) => (
            <RequestCard key={r.id} request={r} onReload={reload} />
          ))}
        </div>
      )}
    </AccountPage>
  );
}
