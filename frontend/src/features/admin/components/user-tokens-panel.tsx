import { useState } from 'react';
import { KeyRound } from 'lucide-react';
import { isRouteMissing } from '@/api/availability';
import { type User } from '@/api/admin-users';
import { useAdminTokens, useRevokeAllUserTokens } from '@/api/hooks/use-tokens';
import { type Token } from '@/api/tokens';
import {
  Button,
  DataTable,
  EmptyState,
  ErrorNotice,
  Notice,
  SkeletonRegion,
  SkeletonRows,
  type DataColumn,
} from '@/ui';
import { isoDate, seenAt } from '../format';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { revokeAllLines, TOKEN_REVOKE_ALL } from '../review-lines';
import { ReviewSlot } from './review-slot';

const COLUMNS: DataColumn<Token>[] = [
  { key: 'name', header: 'Name', cell: (t) => <span className="text-ink">{t.name}</span> },
  { key: 'prefix', header: 'Token', cell: (t) => <span className="font-mono">{t.prefix}…</span> },
  { key: 'created', header: 'Created', cell: (t) => isoDate(t.created_at) },
  { key: 'expires', header: 'Expires', cell: (t) => isoDate(t.expires_at) },
  { key: 'used', header: 'Last used', cell: (t) => seenAt(t.last_used_at) },
];

function NotAvailable() {
  return (
    <Notice icon="·" title="Not available yet">
      Personal access tokens arrive with MCP sign-in. Until then there is nothing to revoke.
    </Notice>
  );
}

/** Phase 4: the user's live tokens and an admin "revoke all" (review first). */
export function UserTokensPanel({ user }: { user: User }) {
  const tokens = useAdminTokens({ user_id: user.id });
  const revokeAll = useRevokeAllUserTokens();
  const write = useReviewedWrite();
  const [missing, setMissing] = useState(false);
  const data = tokens.data;
  if (tokens.isPending) {
    return (
      <SkeletonRegion label="tokens" className="rounded-lg bg-card">
        <SkeletonRows count={3} />
      </SkeletonRegion>
    );
  }
  if (tokens.isError) {
    return (
      <ErrorNotice
        title="Couldn't load tokens"
        onRetry={() => void tokens.refetch()}
        retrying={tokens.isFetching}
      />
    );
  }
  if (missing || (data && !data.available)) return <NotAvailable />;
  const live = data?.available ? data.data.filter((t) => !t.revoked_at) : [];
  const open = () =>
    write.open({
      slot: 'revoke-all',
      title: `Revoke all tokens · ${user.display_name || user.email}`,
      auditAction: TOKEN_REVOKE_ALL,
      lines: revokeAllLines(user.email, live),
      applyLabel: `Revoke ${live.length} tokens`,
      appliedLabel: 'Revoked',
      retryOn409: false,
      run: async () => {
        try {
          return await revokeAll.mutateAsync(user.id);
        } catch (error) {
          if (isRouteMissing(error)) setMissing(true);
          throw error;
        }
      },
    });
  return (
    <div>
      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <span className="text-caption text-muted-foreground">
          {live.length} active tokens · connected apps are listed on the user's own page
        </span>
        <Button variant="pill" className="ml-auto" disabled={!live.length} onClick={open}>
          Revoke all
        </Button>
      </div>
      <ReviewSlot write={write} slot="revoke-all" />
      {live.length > 0 && (
        <DataTable caption="Tokens" columns={COLUMNS} rows={live} rowKey={(t) => t.id} />
      )}
      {data?.available && live.length === 0 && (
        <EmptyState icon={<KeyRound className="h-5 w-5" />} title="No tokens">
          This user has no personal access tokens.
        </EmptyState>
      )}
    </div>
  );
}
