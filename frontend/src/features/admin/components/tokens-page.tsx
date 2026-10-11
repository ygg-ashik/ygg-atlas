import { useState } from 'react';
import { KeyRound } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useMyAccess } from '@/api/hooks/use-my-access';
import {
  useAdminTokens,
  useRevokeAdminToken,
  useRevokeAllUserTokens,
} from '@/api/hooks/use-tokens';
import { type Token, type TokenKindFilter } from '@/api/tokens';
import {
  Button,
  DataTable,
  EmptyState,
  ErrorNotice,
  SegmentedControl,
  SkeletonRegion,
  SkeletonRows,
  type DataColumn,
} from '@/ui';
import { isoDate, plural, seenAt } from '../format';
import { useReviewedWrite, type ReviewedWrite } from '../hooks/use-reviewed-write';
import { revokeAllLines, TOKEN_REVOKE, TOKEN_REVOKE_ALL, tokenRevokeLines } from '../review-lines';
import { AdminPage } from './admin-page';
import { ReviewSlot } from './review-slot';

type KindChoice = 'all' | TokenKindFilter;

const KINDS: { value: KindChoice; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'pat', label: 'Personal' },
  { value: 'service', label: 'Service' },
  { value: 'oauth', label: 'OAuth' },
];

/** Live tokens grouped by owner, in the order the API returned them. */
function byUser(tokens: readonly Token[]): [string, Token[]][] {
  const groups = new Map<string, Token[]>();
  for (const t of tokens) {
    if (t.revoked_at) continue;
    const list = groups.get(t.user_id) ?? [];
    list.push(t);
    groups.set(t.user_id, list);
  }
  return [...groups];
}

/** Admin › Tokens (admin:tokens): everyone's live tokens; revoke one or all of a
 * user's, each reviewed first. Revocations are credential events, not rbac changes. */
export function AdminTokensPage() {
  const [kind, setKind] = useState<KindChoice>('all');
  const tokens = useAdminTokens(kind === 'all' ? {} : { kind });
  const write = useReviewedWrite();
  return (
    <AdminPage
      title="Tokens"
      heading="Tokens"
      sub="Every live token, by owner. A revoked token gets 401 on its next call."
      actions={
        <SegmentedControl
          kind="radio"
          label="Kind"
          value={kind}
          onChange={setKind}
          options={KINDS}
        />
      }
    >
      {tokens.isPending && (
        <SkeletonRegion label="tokens" className="rounded-card bg-card">
          <SkeletonRows count={4} />
        </SkeletonRegion>
      )}
      {tokens.isError && (
        <ErrorNotice
          title="Couldn't load tokens"
          onRetry={() => void tokens.refetch()}
          retrying={tokens.isFetching}
        />
      )}
      {tokens.data && <TokenGroups tokens={tokens.data} write={write} revokeAll={kind === 'all'} />}
    </AdminPage>
  );
}

interface TokenGroupsProps {
  tokens: readonly Token[];
  write: ReviewedWrite;
  /** Only on the unfiltered list: revoke-all revokes every kind, so its review
   * card must list every live token of the user. */
  revokeAll: boolean;
}

function TokenGroups({ tokens, write, revokeAll }: TokenGroupsProps) {
  const groups = byUser(tokens);
  if (!groups.length) {
    return (
      <EmptyState icon={<KeyRound className="h-5 w-5" />} title="No live tokens">
        Nobody holds a live token of this kind.
      </EmptyState>
    );
  }
  return (
    <div className="grid gap-6">
      {!revokeAll && (
        <p className="text-caption text-muted-foreground">
          Revoke all is on the All view: it revokes every token of a user, whatever its kind.
        </p>
      )}
      {groups.map(([userId, list]) => (
        <UserTokens
          key={userId}
          userId={userId}
          tokens={list}
          write={write}
          revokeAll={revokeAll}
        />
      ))}
    </div>
  );
}

interface UserTokensProps {
  userId: string;
  tokens: readonly Token[];
  write: ReviewedWrite;
  revokeAll: boolean;
}

function UserTokens({ userId, tokens, write, revokeAll: canRevokeAll }: UserTokensProps) {
  const view = useMyAccess();
  const revokeOne = useRevokeAdminToken();
  const revokeAll = useRevokeAllUserTokens();
  const one = (t: Token) =>
    write.open({
      slot: `one:${userId}`,
      title: 'Revoke token',
      auditAction: TOKEN_REVOKE,
      lines: tokenRevokeLines(t),
      applyLabel: 'Revoke token',
      appliedLabel: 'Revoked',
      retryOn409: false,
      run: () => revokeOne.mutateAsync(t.id),
    });
  const all = () =>
    write.open({
      slot: `all:${userId}`,
      title: `Revoke all tokens · ${userId}`,
      auditAction: TOKEN_REVOKE_ALL,
      lines: revokeAllLines(userId, tokens),
      applyLabel: `Revoke ${plural(tokens.length, 'token')}`,
      appliedLabel: 'Revoked',
      retryOn409: false,
      run: () => revokeAll.mutateAsync(userId),
    });
  const columns: DataColumn<Token>[] = [
    { key: 'name', header: 'Name', cell: (t) => <span className="text-ink">{t.name}</span> },
    { key: 'kind', header: 'Kind', cell: (t) => <span className="font-mono">{t.kind}</span> },
    { key: 'prefix', header: 'Token', cell: (t) => <span className="font-mono">{t.prefix}…</span> },
    { key: 'created', header: 'Created', cell: (t) => isoDate(t.created_at), hideBelowWide: true },
    { key: 'expires', header: 'Expires', cell: (t) => isoDate(t.expires_at) },
    { key: 'used', header: 'Last used', cell: (t) => seenAt(t.last_used_at) },
    {
      key: 'revoke',
      header: <span className="sr-only">Actions</span>,
      align: 'end',
      cell: (t) => (
        <Button variant="pill" size="sm" aria-label={`Revoke ${t.name}`} onClick={() => one(t)}>
          Revoke
        </Button>
      ),
    },
  ];
  const owner = <span className="font-mono text-[13px]">{userId}</span>;
  return (
    <section aria-label={`Tokens of ${userId}`}>
      <div className="mb-2.5 flex flex-wrap items-center gap-2.5">
        {view.can('admin:users') ? (
          <Link
            to={`/admin/users/${encodeURIComponent(userId)}`}
            className="text-ink underline-offset-2 hover:underline"
          >
            {owner}
          </Link>
        ) : (
          <span className="text-ink">{owner}</span>
        )}
        <span className="text-caption tabular-nums text-muted-foreground">
          {plural(tokens.length, 'live token')}
        </span>
        {canRevokeAll && (
          <Button
            variant="pill"
            size="sm"
            className="ml-auto"
            aria-label={`Revoke all tokens of ${userId}`}
            onClick={all}
          >
            Revoke all
          </Button>
        )}
      </div>
      <ReviewSlot write={write} slot={`all:${userId}`} />
      <DataTable
        caption={`Tokens of ${userId}`}
        columns={columns}
        rows={tokens}
        rowKey={(t) => t.id}
      />
      <ReviewSlot write={write} slot={`one:${userId}`} />
    </section>
  );
}
