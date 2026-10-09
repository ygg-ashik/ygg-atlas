import { Link } from 'react-router-dom';
import { Network } from 'lucide-react';
import { type UserDetail } from '@/api/admin-users';
import { EmptyState, StandingPill, buttonVariants } from '@/ui';
import { CARD, INSET_LIST } from './surfaces';

/** The user's group memberships with their standing. */
export function UserGroupsPanel({ user }: { user: UserDetail }) {
  if (!user.groups.length) {
    return (
      <EmptyState icon={<Network className="h-5 w-5" />} title="Not in any group">
        Groups decide what data people see.
      </EmptyState>
    );
  }
  return (
    <ul aria-label="Groups" className={`${INSET_LIST}`}>
      {user.groups.map((g) => (
        <li
          key={g.id}
          className="flex min-h-[52px] items-center gap-3 border-b border-border/50 px-4 py-2.5 last:border-b-0"
        >
          <span className="min-w-0 flex-1 font-mono text-[13px] text-ink">{g.name}</span>
          <StandingPill standing={g.standing === 'manager' ? 'manager' : 'member'} />
          <Link
            to={`/admin/groups/${g.id}`}
            className={buttonVariants({ variant: 'pill', size: 'sm' })}
            aria-label={`Open ${g.name}`}
          >
            Open
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** The user's own requests: a count here; they are decided in the queue. */
export function UserRequestsPanel({ user }: { user: UserDetail }) {
  return (
    <p className={`${CARD} px-5 py-4 text-sm text-body`}>
      <span className="tabular-nums">{user.pending_requests}</span> pending{' '}
      {user.pending_requests === 1 ? 'request' : 'requests'}.{' '}
      <Link to="/admin/requests" className="text-primary-text underline-offset-4 hover:underline">
        Open the access requests queue
      </Link>{' '}
      to decide them.
    </p>
  );
}
