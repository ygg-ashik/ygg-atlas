import { useState } from 'react';
import { Lock } from 'lucide-react';
import { type RoleInfo } from '@/api/access';
import { type User } from '@/api/admin-users';
import { useUpdateUser } from '@/api/hooks/use-admin-users';
import { Select } from '@/ui';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { roleChangeLines, statusChangeLines } from '../review-lines';
import { ReviewSlot } from './review-slot';

/** The backend's refusal for a self-edit (`_not_self` in app/access/services/users.py). */
export const SELF_EDIT = "You can't change your own role or status. Ask another admin.";

interface RoleStatusEditorProps {
  user: User;
  isSelf: boolean;
  roles: readonly RoleInfo[];
}

type Pending = { field: 'role' | 'status'; value: string } | null;

/** Role and status selects; a change is staged as a review card and written on Apply. */
export function RoleStatusEditor({ user, isSelf, roles }: RoleStatusEditorProps) {
  const write = useReviewedWrite();
  const update = useUpdateUser();
  const [pending, setPending] = useState<Pending>(null);
  const roleNames = roles.length ? roles.map((r) => r.name) : [user.role];

  const stage = (field: 'role' | 'status', value: string) => {
    if (value === user[field]) {
      setPending(null);
      write.dismiss();
      return;
    }
    setPending({ field, value });
    const role = field === 'role';
    write.open({
      slot: 'role',
      title: role ? `Change role · ${user.display_name}` : `Change status · ${user.display_name}`,
      auditAction: role ? 'user.role' : 'user.status',
      lines: role
        ? roleChangeLines(user.email, user.role, value, roles)
        : statusChangeLines(user.email, user.status, value),
      applyLabel: role ? 'Apply role change' : 'Apply status change',
      run: () => update.mutateAsync({ userId: user.id, update: { [field]: value } }),
    });
  };
  const shown = (field: 'role' | 'status') =>
    pending?.field === field ? pending.value : user[field];

  return (
    <>
      <div className="grid min-w-[260px] gap-2">
        <label className="flex items-center gap-2 text-label font-medium text-muted-foreground">
          <span className="w-[52px]">Role</span>
          <Select
            aria-label="Role"
            className="w-full"
            value={shown('role')}
            disabled={isSelf}
            onChange={(e) => stage('role', e.target.value)}
          >
            {roleNames.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex items-center gap-2 text-label font-medium text-muted-foreground">
          <span className="w-[52px]">Status</span>
          <Select
            aria-label="Status"
            className="w-full"
            value={shown('status')}
            disabled={isSelf}
            onChange={(e) => stage('status', e.target.value)}
          >
            <option value="active">active</option>
            <option value="disabled">disabled</option>
          </Select>
        </label>
        {isSelf && (
          <p className="flex max-w-[260px] items-start gap-1.5 text-caption text-body">
            <Lock aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
            {SELF_EDIT}
          </p>
        )}
      </div>
      <div className="basis-full">
        <ReviewSlot write={write} slot="role" onDismiss={() => setPending(null)} />
      </div>
    </>
  );
}
