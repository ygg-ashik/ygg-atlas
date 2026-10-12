import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { type Group, type GroupDetail } from '@/api/admin-groups';
import { useDeleteGroup, useGroupDetail } from '@/api/hooks/use-admin-groups';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { Button, ErrorNotice, Notice, Skeleton, SkeletonRegion, Tag } from '@/ui';
import { plural } from '../format';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { groupDeleteLines } from '../review-lines';
import { GroupForm } from './group-form';
import { GroupGrants } from './group-grants';
import { MembersPanel } from './members-panel';
import { ReviewSlot } from './review-slot';
import { CARD } from './surfaces';
import { ROUTES } from '@/lib/routes';

/** The backend's refusal for deleting a group in use (`delete_group`). */
const IN_USE = "Remove the group's subgroups, members and grants first.";

interface HeaderProps {
  group: GroupDetail;
  subgroups: readonly string[];
  groups: readonly Group[];
  canEdit: boolean;
}

function GroupHeader({ group, subgroups, groups, canEdit }: HeaderProps) {
  const [editing, setEditing] = useState(false);
  const [refused, setRefused] = useState(false);
  const remove = useDeleteGroup();
  const navigate = useNavigate();
  const write = useReviewedWrite();
  const parent = group.path.at(-2) ?? null;
  const inUse = subgroups.length > 0 || group.member_count > 0 || group.grant_count > 0;
  const onDelete = () => {
    if (inUse) return setRefused(true);
    write.open({
      slot: 'delete',
      title: 'Delete group',
      auditAction: 'group.delete',
      lines: groupDeleteLines(group.name, parent),
      applyLabel: 'Delete group',
      appliedLabel: 'Deleted',
      retryOn409: false,
      run: async () => {
        await remove.mutateAsync(group.id);
        navigate(ROUTES.adminGroups);
      },
    });
  };
  return (
    <div className={`${CARD} px-5 py-[18px]`}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-mono text-[19px] text-ink">{group.name}</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{group.description}</p>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <Tag>
              parent {parent ? <span className="font-mono">{parent}</span> : 'none · top level'}
            </Tag>
            {subgroups.length > 0 && <Tag>subgroups {subgroups.join(', ')}</Tag>}
            <Tag>{plural(group.member_count, 'member')}</Tag>
            <Tag>{plural(group.grant_count, 'grant')}</Tag>
          </div>
        </div>
        {canEdit && (
          <div className="flex gap-1.5">
            <Button variant="pill" size="sm" onClick={() => setEditing((v) => !v)}>
              Edit
            </Button>
            <Button variant="pill" size="sm" onClick={onDelete}>
              Delete group
            </Button>
          </div>
        )}
      </div>
      {refused && (
        <Notice role="alert" icon="!" title={IN_USE} className="mt-3.5">
          {group.name} still has {plural(subgroups.length, 'subgroup')},{' '}
          {plural(group.member_count, 'member')} and {plural(group.grant_count, 'grant')}. Deleting
          would silently change what those people can see.
        </Notice>
      )}
      <ReviewSlot write={write} slot="delete" />
      {editing && (
        <div className="mt-3.5">
          <GroupForm group={group} groups={groups} onDone={() => setEditing(false)} />
        </div>
      )}
    </div>
  );
}

interface GroupDetailPanelProps {
  groupId: string;
  groups: readonly Group[];
}

/** One group: header, members, grants. */
export function GroupDetailPanel({ groupId, groups }: GroupDetailPanelProps) {
  const me = useMyAccess();
  const detail = useGroupDetail(groupId);
  const canEdit = me.can('admin:groups');
  if (detail.isPending) {
    return (
      <SkeletonRegion label="the group" className="grid gap-3">
        <Skeleton shape="heading" />
        <Skeleton className="w-2/3" />
      </SkeletonRegion>
    );
  }
  if (detail.isError) {
    return (
      <ErrorNotice
        title="Couldn't load this group"
        onRetry={() => void detail.refetch()}
        retrying={detail.isFetching}
      />
    );
  }
  const group = detail.data;
  const subgroups = groups.filter((g) => g.parent_id === group.id).map((g) => g.name);
  return (
    <div className="grid gap-3.5" key={group.id}>
      <GroupHeader group={group} subgroups={subgroups} groups={groups} canEdit={canEdit} />
      <MembersPanel groupId={group.id} groupName={group.name} />
      <GroupGrants group={group} subgroups={subgroups} canEdit={canEdit} />
    </div>
  );
}
