// Test-only builder for `MyAccessView` personas (src/test: shared test support). Imported only by *.test.tsx.
import { type MeAccess } from '@/api/access';
import { type MyAccessStatus, type MyAccessView } from '@/api/hooks/use-my-access';

const BASE: MeAccess = {
  role: 'viewer',
  capabilities: ['chat:use'],
  groups: [],
  has_data_access: false,
  user_id: 'u1',
  email: 'lina@yougotagift.com',
  display_name: 'Lina Haddad',
  pending_requests: 0,
  pending_approvals: 0,
  is_manager: false,
  clearances: [],
};

/** A view as `useMyAccess` returns it: fails closed unless `status` is ready. */
export function accessView(
  overrides: Partial<MeAccess> = {},
  status: MyAccessStatus = 'ready',
): MyAccessView {
  const access = status === 'ready' ? { ...BASE, ...overrides } : null;
  const capabilities = access?.capabilities ?? [];
  const held = new Set(capabilities);
  return {
    status,
    access,
    capabilities,
    isManager: access?.is_manager ?? false,
    pendingRequests: access?.pending_requests ?? 0,
    pendingApprovals: access?.pending_approvals ?? 0,
    can: (c) => held.has(c),
    canAny: (...wanted) => wanted.some((c) => held.has(c)),
    refetch: () => {},
  };
}

/** The four mockup personas. */
export const PERSONAS = {
  newViewer: accessView(),
  viewer: accessView({ has_data_access: true, pending_requests: 2 }),
  manager: accessView({
    role: 'analyst',
    capabilities: ['chat:use', 'mcp:use', 'tokens:create'],
    is_manager: true,
    has_data_access: true,
    pending_approvals: 3,
  }),
  admin: accessView({
    role: 'admin',
    capabilities: ['chat:use', 'admin:users', 'admin:groups', 'admin:audit'],
    has_data_access: true,
    pending_requests: 1,
    pending_approvals: 5,
  }),
} as const;
