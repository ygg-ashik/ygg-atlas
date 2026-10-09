import { useMemo } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/api/query-client';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { ThemeProvider } from '@/lib/theme-provider';
import { Skeleton, SkeletonRegion, SkeletonRows, Toaster } from '@/ui';
import {
  AuthProvider,
  LoginPage,
  ProtectedRoute,
  RequireAccess,
  useAuth,
  type AccessRule,
} from '@/features/auth';
import { Shell } from '@/features/layout';
import ChatPage, { ChatThreadList } from '@/features/chat';
import { MetricsPage } from '@/features/metrics';
import { CommandPalette, CommandTrigger } from '@/features/command';
import { OverviewPage } from '@/features/dashboard';
import { MyAccessPage, MyRequestsPage, NewRequestPage, TokensPage } from '@/features/account';
import {
  AdminClientsPage,
  AdminRequestsPage,
  AdminTokensPage,
  AuditPage,
  GroupDetailPage,
  GroupsPage,
  UserDetailPage,
  UsersPage,
} from '@/features/admin';
import { ACCESS, ACCOUNT_MENU, buildNav } from './navigation';

/** Composition point: wires auth, access, chat and the command palette into the
 * layout so features stay decoupled. Nav and palette share one filtered list. */
function AppShell() {
  const { user, signOut } = useAuth();
  const view = useMyAccess();
  const nav = useMemo(() => buildNav(view), [view]);
  const role = view.access?.role;
  const shellUser = useMemo(() => (user ? { ...user, role } : null), [user, role]);
  return (
    <Shell
      user={shellUser}
      onSignOut={() => void signOut()}
      nav={nav}
      menuItems={ACCOUNT_MENU}
      threads={
        <>
          <CommandTrigger />
          <ChatThreadList />
        </>
      }
    >
      <Outlet />
      <CommandPalette pages={nav} />
    </Shell>
  );
}

/** Home route: the Overview dashboard, greeted by the signed-in user's name.
 * A first sign-in with no data access (and no admin capability) lands on My
 * access instead, where the way to ask for data is. */
function Home() {
  const { user } = useAuth();
  const view = useMyAccess();
  if (view.status === 'loading') return <HomeSkeleton />;
  const admin = view.capabilities.some((c) => c.startsWith('admin:'));
  if (view.access && !view.access.has_data_access && !admin) {
    return <Navigate to="/account" replace state={{ firstRun: true }} />;
  }
  return <OverviewPage userName={user?.name ?? ''} />;
}

/** Placeholder while `/me/access` decides where a first sign-in lands. */
function HomeSkeleton() {
  return (
    <SkeletonRegion label="your workspace" className="mx-auto max-w-[760px] px-6 pb-16 pt-[84px]">
      <div className="mb-6 mt-1.5 grid gap-2.5">
        <Skeleton shape="heading" />
        <Skeleton className="w-3/5" />
      </div>
      <div className="overflow-hidden rounded-card bg-card shadow-[0_0_0_1px_hsl(var(--border))]">
        <SkeletonRows count={4} />
      </div>
    </SkeletonRegion>
  );
}

/** A route opened only by `rule`; anything else renders the denied page in place. */
function guarded(rule: AccessRule, title: string, page: React.ReactNode) {
  return (
    <RequireAccess rule={rule} title={title}>
      {page}
    </RequireAccess>
  );
}

/** Every route of the signed-in app (exported for the route smoke test). */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<Home />} />
        <Route path="ask/:sessionId?" element={<ChatPage />} />
        <Route path="metrics" element={<MetricsPage />} />
        <Route path="account">
          <Route index element={guarded(ACCESS.account, 'My access', <MyAccessPage />)} />
          <Route
            path="requests"
            element={guarded(ACCESS.account, 'My requests', <MyRequestsPage />)}
          />
          <Route
            path="requests/new"
            element={guarded(ACCESS.account, 'New request', <NewRequestPage />)}
          />
          <Route
            path="tokens"
            element={guarded(ACCESS.account, 'Tokens & connected apps', <TokensPage />)}
          />
        </Route>
        <Route path="admin">
          <Route index element={<Navigate to="/" replace />} />
          <Route path="users" element={guarded(ACCESS.users, 'Users', <UsersPage />)} />
          <Route path="users/:id" element={guarded(ACCESS.users, 'Users', <UserDetailPage />)} />
          <Route path="groups" element={guarded(ACCESS.groups, 'Groups', <GroupsPage />)} />
          <Route
            path="groups/:id"
            element={guarded(ACCESS.groups, 'Groups', <GroupDetailPage />)}
          />
          <Route
            path="requests"
            element={guarded(ACCESS.requests, 'Access requests', <AdminRequestsPage />)}
          />
          <Route path="audit" element={guarded(ACCESS.audit, 'Audit', <AuditPage />)} />
          <Route path="tokens" element={guarded(ACCESS.tokens, 'Tokens', <AdminTokensPage />)} />
          <Route
            path="clients"
            element={guarded(ACCESS.clients, 'OAuth clients', <AdminClientsPage />)}
          />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="light">
        <AuthProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
          <Toaster />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
