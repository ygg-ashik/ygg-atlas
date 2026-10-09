import { useState } from 'react';
import { useRevokeMyToken } from '@/api/hooks/use-tokens';
import { type Token } from '@/api/tokens';
import { Button, DataTable, StatusPill, type DataColumn, type DiffLine } from '@/ui';
import { isoDate, lastUsed } from '../token-format';
import { RevokeReview } from './revoke-review';

const isExpired = (t: Token) => new Date(t.expires_at).getTime() <= Date.now();

function tokenRevokeLines(t: Token): DiffLine[] {
  return [
    { kind: 'context', text: 'token.revoke' },
    { kind: 'remove', text: `token ${t.prefix}…  ${t.name}` },
    { kind: 'context', text: 'anything using it gets 401 on the next call' },
  ];
}

/** The caller's personal tokens (screen 4); each revoke is reviewed first. */
export function TokenList({ tokens }: { tokens: readonly Token[] }) {
  const revoke = useRevokeMyToken();
  const [reviewing, setReviewing] = useState<Token | null>(null);
  const open = (t: Token) => {
    revoke.reset();
    setReviewing(t);
  };
  const columns: DataColumn<Token>[] = [
    {
      key: 'name',
      header: 'Name',
      cell: (t) => <span className="font-medium text-ink">{t.name}</span>,
    },
    { key: 'prefix', header: 'Token', cell: (t) => <span className="font-mono">{t.prefix}…</span> },
    { key: 'created', header: 'Created', cell: (t) => isoDate(t.created_at) },
    {
      key: 'expires',
      header: 'Expires',
      cell: (t) =>
        isExpired(t) ? (
          <span title={`expired ${isoDate(t.expires_at)}`}>
            <StatusPill tone="muted">expired</StatusPill>
          </span>
        ) : (
          isoDate(t.expires_at)
        ),
    },
    { key: 'used', header: 'Last used', cell: (t) => lastUsed(t.last_used_at) },
    {
      key: 'revoke',
      header: <span className="sr-only">Actions</span>,
      align: 'end',
      cell: (t) => (
        <Button variant="pill" size="sm" aria-label={`Revoke ${t.name}`} onClick={() => open(t)}>
          Revoke
        </Button>
      ),
    },
  ];
  return (
    <>
      <DataTable
        caption="Personal access tokens"
        columns={columns}
        rows={tokens}
        rowKey={(t) => t.id}
      />
      {reviewing && (
        <RevokeReview
          title="Revoke token"
          auditAction="token.revoke"
          applyLabel="Revoke token"
          lines={tokenRevokeLines(reviewing)}
          mutation={revoke}
          onApply={() => revoke.mutate(reviewing.id)}
          onDismiss={() => setReviewing(null)}
        />
      )}
    </>
  );
}
