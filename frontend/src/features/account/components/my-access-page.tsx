import { Lock } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { type MeAccess } from '@/api/access';
import { useCapabilityCatalog } from '@/api/hooks/use-capability-catalog';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { Button, EmptyState, ErrorNotice, Skeleton, SkeletonRegion, SkeletonRows, Tag } from '@/ui';
import { AccessSummary } from './access-summary';
import { AccountPage, SectionHeading } from './account-page';

const LIST =
  'overflow-hidden rounded-lg bg-card px-4 py-3 text-[13.5px] text-muted-foreground shadow-[0_0_0_1px_hsl(var(--border)/0.5)]';

/** The greeting name; falls back to the email's local part while the
 * backend's `display_name` is missing or blank. */
function firstName(access: MeAccess | null): string {
  if (!access) return '';
  const name = (access.display_name ?? '').trim();
  if (name) return name.split(/\s+/)[0] ?? '';
  return (access.email ?? '').split('@')[0] ?? '';
}

/** Screen 1 · My access: what Atlas lets the caller do and see, from `/me/access`. */
export function MyAccessPage() {
  const view = useMyAccess();
  const catalog = useCapabilityCatalog();
  const { state } = useLocation() as { state: { firstRun?: boolean } | null };
  const first = state?.firstRun === true && firstName(view.access) !== '';
  const access = view.access;
  return (
    <AccountPage
      title="My access"
      heading={first ? `Welcome to Atlas, ${firstName(access)}` : 'My access'}
      sub={
        first
          ? 'This is where your access lives. You can ask Atlas questions as soon as a group or grant covers the data.'
          : 'What Atlas lets you do and see, and where each permission comes from.'
      }
      action={
        <Button asChild>
          <Link to="/account/requests/new">＋ Request access</Link>
        </Button>
      }
    >
      {view.status === 'loading' && <AccessSkeleton />}
      {view.status === 'unavailable' && (
        <ErrorNotice title="Couldn't load your access" onRetry={view.refetch}>
          The access service didn't answer. Nothing changed; try again in a moment.
        </ErrorNotice>
      )}
      {access && (
        <>
          {!access.has_data_access && <NoDataAccess email={access.email} />}
          <AccessSummary
            access={access}
            catalog={catalog.data}
            catalogFailed={catalog.isError}
            catalogRetrying={catalog.isFetching}
            onRetryCatalog={() => void catalog.refetch()}
          />
          <PendingLink count={access.pending_requests} />
          <WhatICanSee access={access} />
        </>
      )}
    </AccountPage>
  );
}

function NoDataAccess({ email }: { email: string }) {
  return (
    <EmptyState
      className="mb-3.5"
      icon={<Lock className="h-5 w-5" />}
      title="No data access yet"
      actions={
        <Button asChild>
          <Link to="/account/requests/new?kind=group">Request access</Link>
        </Button>
      }
    >
      You're signed in as <b className="font-medium text-ink">{email}</b>, but no group or grant
      covers any data yet, so the chat can't answer metric questions. Ask for the group your team
      uses; its managers see the request.
    </EmptyState>
  );
}

function PendingLink({ count }: { count: number }) {
  if (count < 1) return null;
  return (
    <p className="mt-3 text-[13.5px] text-body">
      <Link to="/account/requests" className="font-medium text-primary-text hover:underline">
        {count === 1 ? '1 pending request' : `${count} pending requests`} →
      </Link>{' '}
      <span className="text-muted-foreground">waiting on a decision.</span>
    </p>
  );
}

/** Rules are not listed here: no self-service endpoint returns them, and the
 * UI never reconstructs access. Clearances come from `/me/access`. */
function WhatICanSee({ access }: { access: MeAccess }) {
  return (
    <>
      <SectionHeading meta="deny wins over allow">What I can see</SectionHeading>
      <p className={LIST}>
        {access.has_data_access
          ? 'Your groups and grants cover data in the catalog. When a question needs something outside them, Atlas says so and offers a request.'
          : 'Nothing yet. Once a request is approved, Atlas answers from that data straight away.'}
      </p>
      <div className="mt-3">
        <ClearanceTags clearances={access.clearances} />
      </div>
    </>
  );
}

function ClearanceTags({ clearances }: { clearances: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-label text-ink">
      <span className="mr-1 font-medium">Clearances</span>
      {clearances.length ? (
        clearances.map((c) => (
          <Tag key={c} mono>
            {c}
          </Tag>
        ))
      ) : (
        <span className="text-muted-foreground">None · names in answers may show masked</span>
      )}
    </div>
  );
}

function AccessSkeleton() {
  return (
    <SkeletonRegion label="your access">
      <div className="mb-3.5 grid gap-3 rounded-card bg-card px-5 py-[18px] shadow-[0_0_0_1px_hsl(var(--border)/0.6)]">
        <div className="flex items-center gap-3.5">
          <Skeleton shape="circle" className="h-12 w-12" />
          <div className="grid flex-1 gap-2">
            <Skeleton className="h-4 w-2/5" />
            <Skeleton className="w-1/4" />
          </div>
        </div>
        <Skeleton className="w-4/5" />
        <Skeleton className="w-2/3" />
      </div>
      <div className="overflow-hidden rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.5)]">
        <SkeletonRows count={3} />
      </div>
    </SkeletonRegion>
  );
}
