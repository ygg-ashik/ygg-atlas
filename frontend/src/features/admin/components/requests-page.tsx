import { Check } from 'lucide-react';
import { type ComponentProps, type ReactNode, useCallback, useMemo, useState } from 'react';
import { useRequestQueue } from '@/api/hooks/use-access-requests';
import { useMyAccess } from '@/api/hooks/use-my-access';
import {
  Button,
  EmptyState,
  ErrorNotice,
  SegmentedControl,
  SkeletonRegion,
  SkeletonRows,
  tabId,
  tabPanelId,
} from '@/ui';
import { stillPendingAfter, type QueueRow } from './request-decision';
import { RequestQueueRow } from './request-queue-row';
import { AdminPage } from './admin-page';

type Tab = 'pending' | 'decided';
const TABS_ID = 'requests';

const newestFirst = (a: QueueRow, b: QueueRow) =>
  Date.parse(b.request.created_at) - Date.parse(a.request.created_at);

/** Screen 10 · Access requests: the requests the viewer may decide (the backend
 * decides which). The Pending count is `/me/access` `pending_approvals`, the
 * same set as the sidebar badge; every decision refreshes both. */
export function AdminRequestsPage() {
  const me = useMyAccess();
  const [tab, setTab] = useState<Tab>('pending');
  // Rows decided on this page keep showing their outcome after the queue
  // refetches without them; cleared when the tab changes.
  const [settled, setSettled] = useState<ReadonlyMap<string, QueueRow>>(new Map());
  const pending = useRequestQueue('pending');
  const decided = useRequestQueue('decided', { enabled: tab === 'decided' });

  const onSettled = useCallback((row: QueueRow) => {
    setSettled((m) => new Map(m).set(row.request.id, row));
  }, []);
  const { refetch } = pending;
  const stillPending = useCallback(
    (requestId: string) => stillPendingAfter(refetch, requestId),
    [refetch],
  );

  const pendingRows = useMemo(() => {
    const live = new Set(pending.items.map((r) => r.id));
    const rows = pending.items.map((r) => settled.get(r.id) ?? { request: r });
    const gone = [...settled.values()].filter((r) => !live.has(r.request.id));
    return [...rows, ...gone].sort(newestFirst);
  }, [pending.items, settled]);
  const decidedRows = useMemo(() => decided.items.map((r) => ({ request: r })), [decided.items]);

  const changeTab = (next: Tab) => {
    setTab(next);
    setSettled(new Map());
  };
  const viewerIsAdmin = me.can('admin:users');
  const sub = viewerIsAdmin
    ? 'Requests from everyone. Approving applies the exact change shown in the review.'
    : 'Group requests for the groups you manage and their subgroups. Role and resource requests go to admins.';
  const query = tab === 'pending' ? pending : decided;

  return (
    <AdminPage title="Access requests" heading="Access requests" sub={sub}>
      <SegmentedControl
        className="mb-3.5"
        label="Requests"
        idBase={TABS_ID}
        value={tab}
        onChange={changeTab}
        options={[
          {
            value: 'pending',
            label: 'Pending',
            count: me.status === 'ready' ? me.pendingApprovals : undefined,
          },
          { value: 'decided', label: 'Decided' },
        ]}
      />
      <div role="tabpanel" id={tabPanelId(TABS_ID, tab)} aria-labelledby={tabId(TABS_ID, tab)}>
        <QueueBody query={query}>
          <QueueList
            rows={tab === 'pending' ? pendingRows : decidedRows}
            tab={tab}
            viewerId={me.access?.user_id ?? null}
            viewerIsAdmin={viewerIsAdmin}
            onSettled={onSettled}
            stillPending={stillPending}
          />
        </QueueBody>
        {query.hasNextPage && (
          <div className="mt-3.5 flex justify-center">
            <Button
              variant="pill"
              onClick={() => void query.fetchNextPage()}
              disabled={query.isFetchingNextPage}
            >
              {query.isFetchingNextPage ? 'Loading…' : 'Load more'}
            </Button>
          </div>
        )}
      </div>
    </AdminPage>
  );
}

type Queue = ReturnType<typeof useRequestQueue>;

/** Skeleton while the first page loads, a stated failure with Retry, else the list. */
function QueueBody({ query, children }: { query: Queue; children: ReactNode }) {
  if (query.isPending) {
    return (
      <SkeletonRegion label="access requests" className="rounded-card bg-card px-[18px] py-3.5">
        <SkeletonRows count={4} />
      </SkeletonRegion>
    );
  }
  if (query.isError && !query.data) {
    return (
      <ErrorNotice
        title="Couldn't load access requests"
        onRetry={() => void query.refetch()}
        retrying={query.isFetching}
      >
        The access service didn&apos;t answer. Nothing changed.
      </ErrorNotice>
    );
  }
  return children;
}

interface QueueListProps extends Omit<ComponentProps<typeof RequestQueueRow>, 'row'> {
  rows: readonly QueueRow[];
  tab: Tab;
}

function QueueList({ rows, tab, ...rowProps }: QueueListProps) {
  if (!rows.length) {
    return tab === 'pending' ? (
      <EmptyState icon={<Check className="h-5 w-5" />} title="No pending requests">
        You&apos;re all caught up. New requests show here and as a count in the account menu.
      </EmptyState>
    ) : (
      <EmptyState icon={<Check className="h-5 w-5" />} title="Nothing decided yet">
        Approved and declined requests show here with their notes.
      </EmptyState>
    );
  }
  return (
    <div className="grid gap-3">
      {rows.map((row) => (
        <RequestQueueRow key={row.request.id} row={row} {...rowProps} />
      ))}
    </div>
  );
}
