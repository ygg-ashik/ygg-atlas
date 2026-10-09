import { useState } from 'react';
import { KeyRound, Lock } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuthMethods } from '@/api/hooks/use-auth-methods';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { useMyTokens } from '@/api/hooks/use-tokens';
import { Button, EmptyState, ErrorNotice, Notice, SkeletonRegion, SkeletonRows } from '@/ui';
import { AccountPage, SectionHeading } from './account-page';
import { ConnectedApps } from './connected-apps';
import { CreateTokenDialog } from './create-token-dialog';
import { TokenList } from './token-list';

const CREATE = 'tokens:create';

/** Screen 4 · Tokens & connected apps: personal tokens, then OAuth apps that act as the caller. */
export function TokensPage() {
  const view = useMyAccess();
  const { methods, isLoading: methodsLoading } = useAuthMethods();
  const tokens = useMyTokens();
  const [creating, setCreating] = useState(false);
  const canCreate = view.can(CREATE) && methods.pat.enabled && tokens.data?.available === true;
  const newToken = () => setCreating(true);
  return (
    <AccountPage
      title="Tokens & connected apps"
      sub="Personal tokens and apps that act as you over MCP. Each sees exactly what you see, never more."
      action={canCreate && <Button onClick={newToken}>＋ New token</Button>}
    >
      <SectionHeading>Personal access tokens</SectionHeading>
      <PersonalTokens
        tokens={tokens}
        loading={tokens.isPending || methodsLoading}
        canCreate={canCreate}
        holdsCapability={view.can(CREATE)}
        role={view.access?.role ?? null}
        onNew={newToken}
      />
      <SectionHeading>Connected apps</SectionHeading>
      <ConnectedApps />
      {canCreate && (
        <CreateTokenDialog open={creating} onOpenChange={setCreating} pat={methods.pat} />
      )}
    </AccountPage>
  );
}

interface PersonalTokensProps {
  tokens: ReturnType<typeof useMyTokens>;
  loading: boolean;
  canCreate: boolean;
  holdsCapability: boolean;
  role: string | null;
  onNew: () => void;
}

function PersonalTokens(props: PersonalTokensProps) {
  const { tokens, loading, canCreate, holdsCapability, role, onNew } = props;
  if (loading || tokens.isPending) {
    return (
      <SkeletonRegion label="your tokens" className="overflow-hidden rounded-card bg-card">
        <SkeletonRows count={3} />
      </SkeletonRegion>
    );
  }
  if (tokens.isError) {
    return (
      <ErrorNotice
        title="Couldn't load your tokens"
        onRetry={() => void tokens.refetch()}
        retrying={tokens.isFetching}
      />
    );
  }
  if (!tokens.data.available) {
    return (
      <Notice icon={<KeyRound className="h-4 w-4" />} title="Not available yet">
        Personal access tokens arrive with MCP sign-in on this deployment.
      </Notice>
    );
  }
  const live = tokens.data.data.filter((t) => !t.revoked_at);
  // Tokens made before a role change can still be revoked without tokens:create.
  if (live.length) return <TokenList tokens={live} />;
  if (!holdsCapability) {
    return (
      <Notice
        icon={<Lock className="h-4 w-4" />}
        title={
          <>
            Personal tokens need <span className="font-mono text-[13px]">{CREATE}</span>
          </>
        }
        action={
          <Button asChild variant="pill">
            <Link to="/account/requests/new?kind=role">Request analyst</Link>
          </Button>
        }
      >
        It comes with the <b className="font-medium text-ink">analyst</b> role.
        {role && ` Your role is ${role}.`}
      </Notice>
    );
  }
  if (!canCreate) {
    return (
      <Notice icon={<KeyRound className="h-4 w-4" />} title="Not enabled for this deployment">
        Personal tokens are turned off here. Sign in to Atlas in the browser instead.
      </Notice>
    );
  }
  return (
    <EmptyState
      icon={<KeyRound className="h-5 w-5" />}
      title="No tokens yet"
      actions={<Button onClick={onNew}>New token</Button>}
    >
      Create a token for scripts or MCP clients that can&apos;t sign in with Google. You see it
      once; Atlas keeps only a hash.
    </EmptyState>
  );
}
