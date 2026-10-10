import { KeyRound } from 'lucide-react';
import { useState } from 'react';
import { useCredentialEvents } from '@/api/hooks/use-credential-events';
import { type CredentialEvent } from '@/api/tokens';
import {
  DataTable,
  type DataColumn,
  EmptyState,
  ErrorNotice,
  SkeletonRegion,
  SkeletonRows,
  Tag,
} from '@/ui';
import { seenAt } from '../format';
import { JsonDetails } from './audit-filters';

/** One page: the route has no cursor, so the tab shows the newest events only. */
const PAGE = { limit: 100 } as const;

const mono = (value: string | null) =>
  value ? (
    <span className="font-mono text-xs">{value}</span>
  ) : (
    <span className="text-muted-foreground">—</span>
  );

const COLUMNS: readonly DataColumn<CredentialEvent>[] = [
  {
    key: 'time',
    header: 'Time (UTC)',
    cell: (e) => <span className="whitespace-nowrap text-muted-foreground">{seenAt(e.at)}</span>,
  },
  {
    key: 'event',
    header: 'Event',
    cell: (e) => <span className="font-mono text-xs text-ink">{e.event}</span>,
  },
  { key: 'via', header: 'Via', cell: (e) => <Tag>{e.via}</Tag> },
  { key: 'user', header: 'User id', cell: (e) => mono(e.user_id) },
  { key: 'token', header: 'Token id', cell: (e) => mono(e.token_id) },
  { key: 'client', header: 'Client id', cell: (e) => mono(e.client_id), hideBelowWide: true },
];

/** Credentials tab: token and client lifecycle events (`credential_events`),
 * newest first. The route has no cursor, so this is the latest page only. */
export function CredentialsTable() {
  const events = useCredentialEvents(PAGE);
  const [open, setOpen] = useState<string | null>(null);
  if (events.isPending) {
    return (
      <SkeletonRegion label="credential events" className="rounded-card bg-card px-[18px] py-3.5">
        <SkeletonRows count={4} />
      </SkeletonRegion>
    );
  }
  if (events.isError) {
    return (
      <ErrorNotice
        title="Couldn't load credential events"
        onRetry={() => void events.refetch()}
        retrying={events.isFetching}
      >
        The access service didn&apos;t answer. Nothing changed.
      </ErrorNotice>
    );
  }
  const rows = events.data;
  if (!rows.length) {
    return (
      <EmptyState icon={<KeyRound className="h-5 w-5" />} title="No credential events yet">
        Token creation, revocation and connected-app changes show here.
      </EmptyState>
    );
  }
  return (
    <>
      {rows.length >= PAGE.limit && (
        <p className="mb-2 text-caption text-muted-foreground">
          The newest {PAGE.limit} events. Older events stay in the log.
        </p>
      )}
      <DataTable
        caption="Credential events"
        columns={COLUMNS}
        rows={rows}
        rowKey={(e) => e.id}
        expandedKey={open}
        onToggleExpand={(key) => setOpen((k) => (k === key ? null : key))}
        renderExpanded={(e) => <JsonDetails label="Details (JSON)" value={e.details} />}
      />
    </>
  );
}
