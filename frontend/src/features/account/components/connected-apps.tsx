import { useState } from 'react';
import { AppWindow } from 'lucide-react';
import { useAuthMethods } from '@/api/hooks/use-auth-methods';
import { useConnectedApps, useRevokeConnectedApp } from '@/api/hooks/use-tokens';
import { CREDENTIAL_EVENT } from '@/api/credential-events';
import { type ConnectedApp } from '@/api/tokens';
import {
  Button,
  ErrorNotice,
  Notice,
  SkeletonRegion,
  SkeletonRows,
  StatusPill,
  type DiffLine,
} from '@/ui';
import { isoDate, lastUsed } from '../token-format';
import { RevokeReview } from './revoke-review';

const LIST =
  'overflow-hidden rounded-card bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_2px_rgba(0,0,0,0.04)]';
const ROW = 'flex items-center gap-3 px-[18px] py-3 [&:not(:last-child)]:border-b border-border/50';

function appRevokeLines(app: ConnectedApp): DiffLine[] {
  return [
    { kind: 'context', text: `${CREDENTIAL_EVENT.familyRevoked}  ${app.client_id}` },
    { kind: 'remove', text: `connected app ${app.client_name} · ${app.redirect_host}` },
    { kind: 'context', text: 'its refresh tokens stop working immediately' },
  ];
}

/** Connected apps (screen 4), driven by the phase-4 flag in `/meta/auth-methods`:
 * disabled → a notice, enabled → the caller's live OAuth grants with Revoke. */
export function ConnectedApps() {
  const { methods, isLoading } = useAuthMethods();
  const enabled = methods.oauth.enabled;
  const apps = useConnectedApps(enabled);
  if (isLoading) return <Loading />;
  if (!enabled) {
    return (
      <Notice
        icon="⌁"
        title="Not enabled for this deployment"
        action={<StatusPill tone="muted">off</StatusPill>}
      >
        Apps like Claude Code connect with your Atlas sign-in (OAuth) once MCP sign-in is turned on.
        Until then, use a personal token.
      </Notice>
    );
  }
  if (apps.isPending) return <Loading />;
  if (apps.isError) {
    return (
      <ErrorNotice
        title="Couldn't load your connected apps"
        onRetry={() => void apps.refetch()}
        retrying={apps.isFetching}
      />
    );
  }
  if (apps.data.length === 0) return <NoApps hosted={methods.oauth.hosted_connectors} />;
  return <AppList apps={apps.data} />;
}

function Loading() {
  return (
    <SkeletonRegion label="connected apps" className={LIST}>
      <SkeletonRows count={2} />
    </SkeletonRegion>
  );
}

function NoApps({ hosted }: { hosted: boolean }) {
  const clients = hosted ? 'Claude Code, claude.ai or Claude Desktop' : 'Claude Code';
  return (
    <div className={LIST}>
      <div className="px-[18px] py-3.5">
        <div className="font-medium text-ink">No connected apps yet</div>
        <p className="mt-0.5 text-[13.5px] text-muted-foreground">
          Connect {clients} to the Atlas MCP server and approve it with your sign-in. It shows up
          here, and you can revoke it any time.
        </p>
      </div>
    </div>
  );
}

function AppList({ apps }: { apps: readonly ConnectedApp[] }) {
  const revoke = useRevokeConnectedApp();
  const [reviewing, setReviewing] = useState<ConnectedApp | null>(null);
  const open = (app: ConnectedApp) => {
    revoke.reset();
    setReviewing(app);
  };
  return (
    <>
      <ul aria-label="Connected apps" className={LIST}>
        {apps.map((app) => (
          <li key={app.family_id} className={ROW}>
            <span
              aria-hidden
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-ink"
            >
              <AppWindow className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-2 font-medium text-ink">
                {app.client_name}
                <span className="font-mono text-xs font-normal text-muted-foreground">
                  {app.client_id}
                </span>
              </div>
              <div className="text-caption tabular-nums text-muted-foreground">
                Authorized {isoDate(app.created_at)} · last used {lastUsed(app.last_used_at)} ·{' '}
                <span className="font-mono">{app.redirect_host}</span>
              </div>
            </div>
            <Button
              variant="pill"
              size="sm"
              aria-label={`Revoke ${app.client_name}`}
              onClick={() => open(app)}
            >
              Revoke
            </Button>
          </li>
        ))}
      </ul>
      {reviewing && (
        <RevokeReview
          title={`Revoke ${reviewing.client_name}`}
          auditAction={CREDENTIAL_EVENT.familyRevoked}
          applyLabel="Revoke app"
          lines={appRevokeLines(reviewing)}
          mutation={revoke}
          onApply={() => revoke.mutate(reviewing.family_id)}
          onDismiss={() => setReviewing(null)}
        />
      )}
    </>
  );
}
