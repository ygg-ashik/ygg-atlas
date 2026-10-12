// src/features/auth/require-access.tsx
import { useIsFetching } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { queryKeys } from '@/api/query-keys';
import {
  Button,
  Morph,
  RouteGuardPage,
  Skeleton,
  SkeletonRegion,
  SkeletonRows,
  Toolbar,
} from '@/ui';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { allows, type AccessRule } from './access-rule';
import { ROUTES, newRequestPath } from '@/lib/routes';

interface RequireAccessProps {
  rule: AccessRule;
  /** Toolbar title while loading or denied, e.g. "Users". */
  title: string;
  children: React.ReactNode;
}

/** Capability route guard. Renders the page only on a backend answer that
 * satisfies `rule`; otherwise the full-page denied notice in place (no redirect,
 * so a deep link can never loop). Loading shows a skeleton; a failed answer is
 * treated as no access. The UI never decides access: the API refuses the rest. */
export function RequireAccess({ rule, title, children }: RequireAccessProps) {
  const view = useMyAccess();
  const { pathname } = useLocation();

  if (view.status === 'loading') return <GuardFrame title={title} route={pathname} busy />;
  if (allows(view, rule)) return <>{children}</>;

  const unavailable = view.status === 'unavailable';
  return (
    <GuardFrame title={title} route={pathname}>
      <RouteGuardPage
        capability={rule.need}
        route={pathname}
        role={view.access?.role ?? 'unconfirmed'}
        actions={unavailable ? <RetryAction onRetry={view.refetch} /> : <DeniedActions />}
      />
    </GuardFrame>
  );
}

function GuardFrame({
  title,
  route,
  busy = false,
  children,
}: {
  title: string;
  route: string;
  busy?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div className="relative h-full">
      <Toolbar title={title} route={route} />
      <div className="absolute inset-0 overflow-y-auto pt-[84px]">
        {busy ? <PageSkeleton title={title} /> : children}
      </div>
    </div>
  );
}

function PageSkeleton({ title }: { title: string }) {
  return (
    <SkeletonRegion label={title} className="mx-auto max-w-[760px] px-6 pb-16">
      <div className="mb-6 mt-1.5 grid gap-2.5">
        <Skeleton shape="heading" />
        <Skeleton className="w-3/5" />
      </div>
      <div className="overflow-hidden rounded-card bg-card shadow-[0_0_0_1px_hsl(var(--border))]">
        <SkeletonRows count={4} />
      </div>
    </SkeletonRegion>
  );
}

function DeniedActions() {
  return (
    <>
      <Button asChild>
        <Link to={ROUTES.access}>Go to My access</Link>
      </Button>
      <Button asChild variant="pill">
        <Link to={newRequestPath({ kind: 'role' })}>Request access</Link>
      </Button>
    </>
  );
}

/** Same behaviour as ui ErrorNotice: the pill morphs to "Loading…" while the
 * access answer is refetching, and stays disabled until it lands. */
function RetryAction({ onRetry }: { onRetry: () => void }) {
  const retrying = useIsFetching({ queryKey: queryKeys.myAccess }) > 0;
  return (
    <Button
      type="button"
      variant="pill"
      onClick={onRetry}
      disabled={retrying}
      aria-label={retrying ? 'Loading' : 'Retry'}
    >
      <Morph done={retrying} from="↻ Retry" to="Loading…" />
    </Button>
  );
}
