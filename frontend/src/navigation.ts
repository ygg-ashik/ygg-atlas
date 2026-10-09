// src/navigation.ts
// App-level composition: which routes need what, and the navigation built from
// the backend's `/me/access` answer. The route guards (App.tsx), the
// sidebar and the command palette all read these, so they never disagree.
import {
  ArrowLeftRight,
  History,
  Inbox,
  KeyRound,
  LayoutDashboard,
  Library,
  MessageCircle,
  Network,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { allows, type AccessRule } from '@/features/auth';
import { type AccountMenuItem, type NavBadge, type NavItem } from '@/features/layout';

/** Route access rules (backend capabilities; managers where the backend lets them act). */
export const ACCESS = {
  /** Every signed-in user; a failed `/me/access` still fails closed. */
  account: { anyOf: [], need: 'chat:use' },
  users: { anyOf: ['admin:users'], need: 'admin:users' },
  groups: { anyOf: ['admin:groups'], managers: true, need: 'admin:groups' },
  /** Backend `decidable_scope`: admin:users, admin:groups, or manager standing. */
  requests: { anyOf: ['admin:users', 'admin:groups'], managers: true, need: 'admin:users' },
  audit: { anyOf: ['admin:audit'], need: 'admin:audit' },
} as const satisfies Record<string, AccessRule>;

const PRIMARY: NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/ask', label: 'Ask Atlas', icon: MessageCircle },
  { to: '/metrics', label: 'Metrics', icon: Library },
];

export const ACCOUNT_MENU: AccountMenuItem[] = [
  { to: '/account', label: 'My access', icon: ShieldCheck },
  { to: '/account/tokens', label: 'Tokens & apps', icon: KeyRound },
];

/** Screen-reader meaning of a count badge, singular or plural ("1 pending request"). */
function countBadge(count: number, one: string, many: string): NavBadge {
  return { count, label: count === 1 ? one : many };
}

function accountItems(view: MyAccessView): NavItem[] {
  const section = 'Account';
  return [
    { to: '/account', label: 'My access', icon: ShieldCheck, section, end: true },
    {
      to: '/account/requests',
      label: 'My requests',
      icon: ArrowLeftRight,
      section,
      badge: countBadge(view.pendingRequests, 'pending request', 'pending requests'),
    },
    { to: '/account/tokens', label: 'Tokens & apps', icon: KeyRound, section },
  ];
}

function adminItems(view: MyAccessView): NavItem[] {
  const section = 'Admin';
  const candidates: { rule: AccessRule; item: NavItem }[] = [
    { rule: ACCESS.users, item: { to: '/admin/users', label: 'Users', icon: Users, section } },
    { rule: ACCESS.groups, item: { to: '/admin/groups', label: 'Groups', icon: Network, section } },
    {
      rule: ACCESS.requests,
      item: {
        to: '/admin/requests',
        label: 'Access requests',
        icon: Inbox,
        section,
        // Requests the viewer can decide, never their own: the same set as the queue's tab.
        badge: countBadge(view.pendingApprovals, 'request to decide', 'requests to decide'),
      },
    },
    { rule: ACCESS.audit, item: { to: '/admin/audit', label: 'Audit', icon: History, section } },
  ];
  return candidates.filter(({ rule }) => allows(view, rule)).map(({ item }) => item);
}

/** Primary, Account, then the Admin section with only the entries the viewer
 * can open. No admin entries while access is loading or unavailable (fail closed). */
export function buildNav(view: MyAccessView): NavItem[] {
  return [...PRIMARY, ...accountItems(view), ...adminItems(view)];
}
