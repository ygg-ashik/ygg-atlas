// src/navigation.ts
// App-level composition: which routes need what, and the navigation built from
// the backend's `/me/access` answer. The route guards (App.tsx), the sidebar,
// the settings rail, the account menu and the command palette all read these,
// so they never disagree. Paths come from `lib/routes`.
import {
  ArrowLeftRight,
  History,
  Inbox,
  KeyRound,
  KeySquare,
  LayoutDashboard,
  Library,
  MessageCircle,
  Network,
  Plug,
  Settings2,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { allows, type AccessRule } from '@/features/auth';
import { type AdminEntry, type NavItem, type NavSection } from '@/features/layout';
import { ROUTES } from '@/lib/routes';

/** Route access rules (backend capabilities; managers where the backend lets them act). */
export const ACCESS = {
  /** Every signed-in user; a failed `/me/access` still fails closed. */
  account: { anyOf: [], need: 'chat:use' },
  users: { anyOf: ['admin:users'], need: 'admin:users' },
  groups: { anyOf: ['admin:groups'], managers: true, need: 'admin:groups' },
  /** Backend `decidable_scope`: admin:users, admin:groups, or manager standing. */
  requests: { anyOf: ['admin:users', 'admin:groups'], managers: true, need: 'admin:users' },
  audit: { anyOf: ['admin:audit'], need: 'admin:audit' },
  tokens: { anyOf: ['admin:tokens'], need: 'admin:tokens' },
  clients: { anyOf: ['admin:clients'], need: 'admin:clients' },
} as const satisfies Record<string, AccessRule>;

export const PRIMARY_NAV: NavItem[] = [
  { to: ROUTES.home, label: 'Overview', icon: LayoutDashboard },
  { to: ROUTES.ask, label: 'Ask Atlas', icon: MessageCircle },
  { to: ROUTES.metrics, label: 'Metrics', icon: Library },
];

const YOU: NavItem[] = [
  { to: ROUTES.settings, label: 'General', icon: Settings2 },
  { to: ROUTES.access, label: 'My access', icon: ShieldCheck },
  { to: ROUTES.requests, label: 'Requests', icon: ArrowLeftRight },
  { to: ROUTES.tokens, label: 'Tokens & apps', icon: KeyRound },
];

function organization(view: MyAccessView): NavItem[] {
  const n = view.pendingApprovals;
  const candidates: { rule: AccessRule; item: NavItem }[] = [
    { rule: ACCESS.users, item: { to: ROUTES.adminUsers, label: 'Users', icon: Users } },
    { rule: ACCESS.groups, item: { to: ROUTES.adminGroups, label: 'Groups', icon: Network } },
    {
      rule: ACCESS.requests,
      item: {
        to: ROUTES.adminRequests,
        label: 'Access requests',
        icon: Inbox,
        // Requests the viewer can decide, never their own: the same set as the queue's tab.
        badge: { count: n, label: n === 1 ? 'request to decide' : 'requests to decide' },
      },
    },
    { rule: ACCESS.audit, item: { to: ROUTES.adminAudit, label: 'Audit', icon: History } },
    { rule: ACCESS.tokens, item: { to: ROUTES.adminTokens, label: 'Tokens', icon: KeySquare } },
    {
      rule: ACCESS.clients,
      item: { to: ROUTES.adminClients, label: 'OAuth clients', icon: Plug },
    },
  ];
  return candidates.filter(({ rule }) => allows(view, rule)).map(({ item }) => item);
}

/** The settings rail: You, then Organization with only the pages the viewer can
 * open. No Organization group while access is loading or unavailable (fail closed). */
export function buildSettingsNav(view: MyAccessView): NavSection[] {
  const org = organization(view);
  const you: NavSection = { title: 'You', items: YOU };
  return org.length ? [you, { title: 'Organization', items: org }] : [you];
}

/** Every page the palette may offer: the primary nav, then "Settings › …". */
export function buildPalettePages(view: MyAccessView): { label: string; to: string }[] {
  const settings = buildSettingsNav(view).flatMap((s) => s.items);
  return [
    ...PRIMARY_NAV.map(({ label, to }) => ({ label, to })),
    ...settings.map(({ label, to }) => ({ label: `Settings › ${label}`, to })),
  ];
}

/** True when the viewer holds any `admin:*` capability (false until access answers). */
export function isAdmin(view: MyAccessView): boolean {
  return view.capabilities.some((c) => c.startsWith('admin:'));
}

/** The account menu's Admin item: managers and holders of any `admin:*`
 * capability. It opens the queue when something waits, else the first page. */
export function adminEntry(view: MyAccessView): AdminEntry | undefined {
  if (view.status !== 'ready' || !(isAdmin(view) || view.isManager)) return undefined;
  const pages = organization(view);
  const queue = pages.find((p) => p.to === ROUTES.adminRequests);
  const to = view.pendingApprovals > 0 && queue ? queue.to : pages[0]?.to;
  return to ? { to, pendingApprovals: view.pendingApprovals } : undefined;
}
