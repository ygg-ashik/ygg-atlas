import { useCapabilityCatalog } from '@/api/hooks/use-capability-catalog';
import { type UserDetail } from '@/api/admin-users';
import {
  Avatar,
  ErrorNotice,
  SegmentedControl,
  Skeleton,
  SkeletonRegion,
  SkeletonRows,
  Tag,
  tabId,
  tabPanelId,
} from '@/ui';
import { isoDate, plural, seenAt } from '../format';
import { useUserDetailView, type UserTab } from '../hooks/use-user-detail';
import { AdminPage } from './admin-page';
import { AttributesEditor } from './attributes-editor';
import { DirectGrants } from './direct-grants';
import { EffectiveAccessPanel } from './effective-access-panel';
import { RoleStatusEditor } from './role-status-editor';
import { UserGroupsPanel, UserRequestsPanel } from './user-groups-panel';
import { UserTokensPanel } from './user-tokens-panel';
import { CARD } from './surfaces';

const TABS_ID = 'user-detail';

function Header({ user, isSelf }: { user: UserDetail; isSelf: boolean }) {
  const roles = useCapabilityCatalog().data?.roles ?? [];
  const name = user.display_name || user.email;
  return (
    <div className={`${CARD} px-[22px] py-5`}>
      <div className="flex flex-wrap items-start gap-4">
        <Avatar name={name} size="lg" kind={user.kind === 'service' ? 'service' : 'human'} />
        <div className="min-w-[220px] flex-1">
          <h2 className="flex items-center gap-2 font-serif text-[27px] leading-tight text-ink">
            {name}
            {isSelf && <Tag>you</Tag>}
          </h2>
          <div className="text-[13.5px] text-muted-foreground">{user.email}</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Tag>{user.kind}</Tag>
            <Tag>created {isoDate(user.created_at)}</Tag>
            <Tag>last seen {seenAt(user.last_seen_at)}</Tag>
            <Tag>{plural(user.groups.length, 'group')}</Tag>
          </div>
        </div>
        <RoleStatusEditor user={user} isSelf={isSelf} roles={roles} />
      </div>
    </div>
  );
}

function TabPanel({ tab, user, isSelf }: { tab: UserTab; user: UserDetail; isSelf: boolean }) {
  switch (tab) {
    case 'grants':
      return <DirectGrants user={user} isSelf={isSelf} />;
    case 'effective':
      return (
        <>
          <EffectiveAccessPanel user={user} />
          <AttributesEditor user={user} />
        </>
      );
    case 'tokens':
      return <UserTokensPanel user={user} />;
    case 'requests':
      return <UserRequestsPanel user={user} />;
    default:
      return <UserGroupsPanel user={user} />;
  }
}

function DetailSkeleton() {
  return (
    <SkeletonRegion label="this user" className="grid gap-3.5">
      <div className="flex items-center gap-3 rounded-card bg-card p-5">
        <Skeleton shape="circle" className="h-12 w-12" />
        <div className="grid flex-1 gap-2">
          <Skeleton className="h-4 w-2/5" />
          <Skeleton className="w-1/4" />
        </div>
      </div>
      <div className="rounded-lg bg-card">
        <SkeletonRows count={4} />
      </div>
    </SkeletonRegion>
  );
}

/** Screen 7 (and 8 at `?tab=effective`): one user, their role, groups, grants and access. */
export function UserDetailPage() {
  const { tab, setTab, detail, isSelf } = useUserDetailView();
  const user = detail.data;
  return (
    <AdminPage title={user ? user.display_name || user.email : 'User'}>
      {detail.isPending && <DetailSkeleton />}
      {detail.isError && (
        <ErrorNotice
          title="Couldn't load this user"
          onRetry={() => void detail.refetch()}
          retrying={detail.isFetching}
        />
      )}
      {user && (
        <>
          <Header user={user} isSelf={isSelf} />
          <SegmentedControl<UserTab>
            className="my-[18px]"
            label="User sections"
            idBase={TABS_ID}
            value={tab}
            onChange={setTab}
            options={[
              { value: 'groups', label: 'Groups', count: user.groups.length },
              { value: 'grants', label: 'Direct grants', count: user.direct_grants.length },
              { value: 'effective', label: 'Effective access' },
              { value: 'tokens', label: 'Tokens' },
              { value: 'requests', label: 'Requests', count: user.pending_requests },
            ]}
          />
          <div
            role="tabpanel"
            id={tabPanelId(TABS_ID, tab)}
            aria-labelledby={tabId(TABS_ID, tab)}
            className="animate-materialize-in"
          >
            <TabPanel tab={tab} user={user} isSelf={isSelf} />
          </div>
        </>
      )}
    </AdminPage>
  );
}
