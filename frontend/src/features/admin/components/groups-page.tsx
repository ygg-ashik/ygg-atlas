import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Network } from 'lucide-react';
import { type Group } from '@/api/admin-groups';
import { useGroups } from '@/api/hooks/use-admin-groups';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { Button, EmptyState, ErrorNotice, Skeleton, SkeletonRegion } from '@/ui';
import { buildGroupTree } from '../group-tree';
import { AdminPage } from './admin-page';
import { GroupDetailPanel } from './group-detail-page';
import { GroupForm } from './group-form';
import { GroupTree } from './group-tree';

/** `GET /admin/groups`: every group for admin:groups; for a group manager,
 * the groups they manage and their subgroups, with real parent ids (P5-D22).
 * A managed group whose parent is outside that set shows as a root. */
function useVisibleGroups() {
  const me = useMyAccess();
  const admin = me.can('admin:groups');
  const list = useGroups({ enabled: admin || me.isManager });
  return { admin, list, groups: list.data ?? [], ready: list.isSuccess };
}

function GroupsSkeleton() {
  return (
    <SkeletonRegion label="groups" className="grid gap-3 min-[900px]:grid-cols-[300px_1fr]">
      <div className="grid gap-3 rounded-card bg-card p-3.5">
        {[60, 45, 70, 50].map((w) => (
          <Skeleton key={w} style={{ width: `${w}%` }} className="h-3.5" />
        ))}
      </div>
      <Skeleton shape="heading" />
    </SkeletonRegion>
  );
}

interface BodyProps {
  groups: readonly Group[];
  selected: string | null;
  creating: boolean;
}

function GroupsBody({ groups, selected, creating }: BodyProps) {
  const navigate = useNavigate();
  if (groups.length === 0) {
    return creating ? null : (
      <EmptyState icon={<Network className="h-5 w-5" />} title="No groups yet">
        Groups hold the data grants; members inherit them. Start with your teams.
      </EmptyState>
    );
  }
  return (
    <div className="grid items-start gap-3.5 min-[900px]:grid-cols-[300px_1fr]">
      <GroupTree
        groups={groups}
        selectedId={selected}
        onSelect={(next) => navigate(`/admin/groups/${next}`)}
      />
      {selected && <GroupDetailPanel groupId={selected} groups={groups} />}
    </div>
  );
}

/** Screen 9: the group tree on the left, the selected group on the right. */
function GroupsWorkspace() {
  const { id } = useParams();
  const { admin, list, groups, ready } = useVisibleGroups();
  const [creating, setCreating] = useState(false);
  const selected = id ?? buildGroupTree(groups)[0]?.group.id ?? null;
  return (
    <AdminPage
      title="Groups"
      heading="Groups"
      sub={
        admin
          ? 'Groups hold data grants; members inherit them and everything from parent groups.'
          : 'Groups you manage. You can add and remove plain members; grants are managed by admins.'
      }
      actions={admin && <Button onClick={() => setCreating(true)}>＋ New group</Button>}
    >
      {creating && <GroupForm groups={groups} onDone={() => setCreating(false)} />}
      {list.isError && (
        <ErrorNotice
          title="Couldn't load groups"
          onRetry={() => void list.refetch()}
          retrying={list.isFetching}
        />
      )}
      {!list.isError && !ready && <GroupsSkeleton />}
      {ready && <GroupsBody groups={groups} selected={selected} creating={creating} />}
    </AdminPage>
  );
}

export const GroupsPage = GroupsWorkspace;
export const GroupDetailPage = GroupsWorkspace;
