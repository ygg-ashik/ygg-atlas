import { Plug } from 'lucide-react';
import { useClients, useRevokeClient } from '@/api/hooks/use-tokens';
import { type OAuthClient } from '@/api/tokens';
import {
  Button,
  DataTable,
  EmptyState,
  ErrorNotice,
  Notice,
  SkeletonRegion,
  SkeletonRows,
  StatusPill,
  type DataColumn,
} from '@/ui';
import { isoDate } from '../format';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { clientRevokeLines } from '../review-lines';
import { AdminPage } from './admin-page';
import { ReviewSlot } from './review-slot';

/** `http://localhost:33418/callback` → `localhost`; unparseable → as given. */
function redirectHosts(uris: readonly string[]): string {
  const hosts = uris.map((u) => {
    try {
      return new URL(u).hostname;
    } catch {
      return u;
    }
  });
  return [...new Set(hosts)].join(', ');
}

/** Admin › OAuth clients (admin:clients): registered MCP clients; revoking one
 * ends every connected sign-in through it, reviewed first. */
export function AdminClientsPage() {
  const clients = useClients();
  const revoke = useRevokeClient();
  const write = useReviewedWrite();
  const open = (c: OAuthClient) =>
    write.open({
      slot: 'client',
      title: `Revoke ${c.client_name}`,
      auditAction: 'client.revoke',
      lines: clientRevokeLines(c, c.active_families),
      applyLabel: 'Revoke client',
      appliedLabel: 'Revoked',
      retryOn409: false,
      run: () => revoke.mutateAsync(c.client_id),
    });
  const columns: DataColumn<OAuthClient>[] = [
    {
      key: 'name',
      header: 'Client',
      cell: (c) => (
        <div>
          <div className="text-ink">{c.client_name}</div>
          <div className="font-mono text-xs text-muted-foreground">{c.client_id}</div>
        </div>
      ),
    },
    {
      key: 'redirect',
      header: 'Redirects to',
      cell: (c) => <span className="font-mono">{redirectHosts(c.redirect_uris)}</span>,
    },
    { key: 'registered', header: 'Registered', cell: (c) => isoDate(c.registered_at) },
    { key: 'families', header: 'Live sign-ins', align: 'end', cell: (c) => c.active_families },
    {
      key: 'status',
      header: 'Status',
      cell: (c) =>
        c.revoked_at ? (
          <StatusPill tone="muted" diamond>
            revoked
          </StatusPill>
        ) : (
          <StatusPill tone="positive">active</StatusPill>
        ),
    },
    {
      key: 'revoke',
      header: <span className="sr-only">Actions</span>,
      align: 'end',
      cell: (c) =>
        !c.revoked_at && (
          <Button
            variant="pill"
            size="sm"
            aria-label={`Revoke ${c.client_name}`}
            onClick={() => open(c)}
          >
            Revoke
          </Button>
        ),
    },
  ];
  return (
    <AdminPage
      title="OAuth clients"
      heading="OAuth clients"
      sub="MCP clients registered with Atlas. Revoking one signs out everyone connected through it."
    >
      {clients.isPending && (
        <SkeletonRegion label="clients" className="rounded-card bg-card">
          <SkeletonRows count={3} />
        </SkeletonRegion>
      )}
      {clients.isError && (
        <ErrorNotice
          title="Couldn't load clients"
          onRetry={() => void clients.refetch()}
          retrying={clients.isFetching}
        />
      )}
      {clients.data && !clients.data.available && (
        <Notice icon={<Plug className="h-4 w-4" />} title="Not available yet">
          OAuth clients arrive with MCP sign-in on this deployment.
        </Notice>
      )}
      {clients.data?.available && clients.data.data.length === 0 && (
        <EmptyState icon={<Plug className="h-5 w-5" />} title="No clients registered">
          A client appears here the first time someone connects an MCP app with their sign-in.
        </EmptyState>
      )}
      {clients.data?.available && clients.data.data.length > 0 && (
        <>
          <ReviewSlot write={write} slot="client" />
          <DataTable
            caption="OAuth clients"
            columns={columns}
            rows={clients.data.data}
            rowKey={(c) => c.client_id}
          />
        </>
      )}
    </AdminPage>
  );
}
