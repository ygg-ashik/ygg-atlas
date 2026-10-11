import { type GroupStanding } from '@/api/access';
import { type Member } from '@/api/admin-groups';
import { useGroupMembers, usePutMember, useRemoveMember } from '@/api/hooks/use-admin-groups';
import { useMyAccess } from '@/api/hooks/use-my-access';
import {
  Avatar,
  Button,
  ErrorNotice,
  SkeletonRegion,
  SkeletonRows,
  StandingPill,
  StatusPill,
  Tag,
} from '@/ui';
import { plural } from '../format';
import { useReviewedWrite, type ReviewedWrite } from '../hooks/use-reviewed-write';
import { memberPutLines, memberRemoveLines } from '../review-lines';
import { MemberPicker, PickerDenied, type PickedPerson, type PickerSource } from './member-picker';
import { ReviewSlot } from './review-slot';
import { INSET_LIST } from './surfaces';

interface MembersPanelProps {
  groupId: string;
  groupName: string;
}

interface Authority {
  meId: string | null;
  admin: boolean;
}

/** What the viewer may do to one row. The API enforces the same rules (D8, D10). */
function rowAction(m: Member, who: Authority): 'remove' | 'self' | 'manager-only' | null {
  const self = m.user_id === who.meId;
  if (self) return who.admin ? null : 'self';
  if (who.admin) return 'remove';
  return m.standing === 'member' ? 'remove' : 'manager-only';
}

interface RowProps {
  m: Member;
  who: Authority;
  onRemove: (m: Member) => void;
}

function MemberRow({ m, who, onRemove }: RowProps) {
  const name = m.display_name || m.email;
  const action = rowAction(m, who);
  return (
    <li
      aria-label={name}
      className="flex min-h-[52px] items-center gap-3 border-b border-border/50 px-4 py-2.5 last:border-b-0"
    >
      <Avatar name={name} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-[14.5px] font-medium text-ink">
          {name}
          {m.user_id === who.meId && <Tag>you</Tag>}
          {m.status === 'disabled' && <StatusPill>disabled</StatusPill>}
        </div>
        <div className="truncate text-[12.5px] text-muted-foreground">{m.email}</div>
      </div>
      <StandingPill standing={m.standing} />
      {action === 'remove' && (
        <Button variant="pill" size="sm" aria-label={`Remove ${name}`} onClick={() => onRemove(m)}>
          Remove
        </Button>
      )}
      {action === 'self' && (
        <span className="max-w-[170px] text-right text-caption text-muted-foreground">
          Managers can't change their own membership
        </span>
      )}
      {action === 'manager-only' && (
        <span className="text-caption text-muted-foreground">manager · admin only</span>
      )}
    </li>
  );
}

function useMemberWrites(
  write: ReviewedWrite,
  groupId: string,
  groupName: string,
  members: Member[],
) {
  const put = usePutMember();
  const remove = useRemoveMember();
  const add = (u: PickedPerson, standing: GroupStanding) => {
    const existing = members.find((m) => m.user_id === u.id)?.standing ?? null;
    write.open({
      slot: 'member',
      title: 'Add member',
      auditAction: 'member.put',
      lines: memberPutLines(groupName, u.email, existing, standing),
      applyLabel: 'Add member',
      appliedLabel: 'Added',
      run: () => put.mutateAsync({ groupId, userId: u.id, standing }),
    });
  };
  const drop = (m: Member) =>
    write.open({
      slot: 'member',
      title: 'Remove member',
      auditAction: 'member.remove',
      lines: memberRemoveLines(groupName, m.email, m.standing),
      applyLabel: 'Remove',
      appliedLabel: 'Removed',
      run: () => remove.mutateAsync({ groupId, userId: m.user_id }),
    });
  return { add, drop };
}

/** admin:users searches every user; a member-admin (admin:groups or a manager)
 * searches the group's candidates, where the backend checks this exact group. */
function pickerSource(adminUsers: boolean, memberAdmin: boolean): PickerSource | null {
  if (adminUsers) return 'users';
  return memberAdmin ? 'candidates' : null;
}

/** Members of one group. Managers add and remove plain members only; admin:groups does the rest. */
export function MembersPanel({ groupId, groupName }: MembersPanelProps) {
  const me = useMyAccess();
  const members = useGroupMembers(groupId);
  const write = useReviewedWrite();
  const list = members.data ?? [];
  const { add, drop } = useMemberWrites(write, groupId, groupName, list);
  const who: Authority = { meId: me.access?.user_id ?? null, admin: me.can('admin:groups') };
  const source = pickerSource(me.can('admin:users'), who.admin || me.isManager);
  return (
    <section aria-label="Members">
      <h3 className="mb-2.5 mt-1.5 flex flex-wrap items-baseline gap-2 font-serif text-section text-ink">
        Members
        <span className="font-sans text-caption tabular-nums text-muted-foreground">
          {plural(list.length, 'member')} · managers decide requests for this subtree
        </span>
      </h3>
      {source ? (
        <MemberPicker groupId={groupId} source={source} canAppoint={who.admin} onPick={add} />
      ) : (
        <PickerDenied />
      )}
      <ReviewSlot write={write} slot="member" />
      {members.isPending && (
        <SkeletonRegion label="members" className="rounded-lg bg-card">
          <SkeletonRows count={3} />
        </SkeletonRegion>
      )}
      {members.isError && (
        <ErrorNotice
          title="Couldn't load members"
          onRetry={() => void members.refetch()}
          retrying={members.isFetching}
        />
      )}
      {members.isSuccess && (
        <ul aria-label={`Members of ${groupName}`} className={`${INSET_LIST}`}>
          {list.length === 0 && (
            <li className="px-4 py-3 text-[13.5px] text-muted-foreground">No members yet.</li>
          )}
          {list.map((m) => (
            <MemberRow key={m.user_id} m={m} who={who} onRemove={drop} />
          ))}
        </ul>
      )}
    </section>
  );
}
