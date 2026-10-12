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
import { CommandTrigger } from '@/features/command';
import { OverviewPage } from '@/features/dashboard';
import {
  GeneralPage,
  MyAccessPage,
  MyRequestsPage,
  NewRequestPage,
  TokensPage,
} from '@/features/account';
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
import { ConsentPage } from '@/features/oauth-consent';
import { RequestAccessProvider } from '@/lib/request-access';
import { ROUTES } from '@/lib/routes';
import { ACCESS, PRIMARY_NAV, adminEntry, buildPalettePages, buildSettingsNav } from './navigation';
import { QuickDialogs, QuickPalette, useQuickDialogs } from './quick-actions';

/** Composition point: wires auth, access, chat, settings and the command palette
 * into the layout so features stay decoupled. Navigation, the settings rail, the
 * account menu and the palette all come from the same `/me/access` answer. */
function AppShell() {
  const { user, signOut } = useAuth();
  const view = useMyAccess();
  const dialogs = useQuickDialogs();
  const settings = useMemo(() => buildSettingsNav(view), [view]);
  const pages = useMemo(() => buildPalettePages(view), [view]);
  const admin = useMemo(() => adminEntry(view), [view]);
  const role = view.access?.role;
  const shellUser = useMemo(() => (user ? { ...user, role } : null), [user, role]);
  return (
    <RequestAccessProvider value={dialogs.requestAccess}>
      <Shell
        user={shellUser}
        onSignOut={() => void signOut()}
        nav={PRIMARY_NAV}
        settings={settings}
        admin={admin}
        threads={
          <>
            <CommandTrigger />
            <ChatThreadList />
          </>
        }
      >
        <Outlet />
        <QuickPalette view={view} pages={pages} onRun={dialogs.setOpen} />
        <QuickDialogs view={view} open={dialogs.open} close={dialogs.close} />
      </Shell>
    </RequestAccessProvider>
  );
}

/** Home route: the Overview dashboard, greeted by the signed-in user's name. A
 * viewer with no data access (and no admin capability) gets the chat instead,
 * whose first-run empty state offers the request in place. */
function Home() {
  const { user } = useAuth();
  const view = useMyAccess();
  if (view.status === 'loading') return <HomeSkeleton />;
  const admin = view.capabilities.some((c) => c.startsWith('admin:'));
  if (view.access && !view.access.has_data_access && !admin) return <ChatPage />;
  return <OverviewPage userName={user?.name ?? ''} />;
}

/** Settings › General: the account feature's page with the auth feature's session. */
function GeneralSettings() {
  const { user, signOut } = useAuth();
  return <GeneralPage email={user?.email ?? ''} onSignOut={() => void signOut()} />;
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

/** Every route of the signed-in app (exported for the route smoke test). Paths
 * come from `lib/routes`; there are no redirects from retired paths. */
export function AppRoutes() {
  return (
    <Routes>
      <Route path={ROUTES.login} element={<LoginPage />} />
      <Route path={ROUTES.consent} element={<OAuthConsent />} />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<Home />} />
        <Route path={ROUTES.askThread} element={<ChatPage />} />
        <Route path={ROUTES.metrics} element={<MetricsPage />} />
        {/* Settings › You: every signed-in user. */}
        <Route
          path={ROUTES.settings}
          element={guarded(ACCESS.account, 'General', <GeneralSettings />)}
        />
        <Route
          path={ROUTES.access}
          element={guarded(ACCESS.account, 'My access', <MyAccessPage />)}
        />
        <Route
          path={ROUTES.requests}
          element={guarded(ACCESS.account, 'Requests', <MyRequestsPage />)}
        />
        <Route
          path={ROUTES.newRequest}
          element={guarded(ACCESS.account, 'New request', <NewRequestPage />)}
        />
        <Route
          path={ROUTES.tokens}
          element={guarded(ACCESS.account, 'Tokens & connected apps', <TokensPage />)}
        />
        {/* Settings › Organization: each behind its capability rule, failing closed. */}
        <Route path={ROUTES.adminUsers} element={guarded(ACCESS.users, 'Users', <UsersPage />)} />
        <Route
          path={ROUTES.adminUser}
          element={guarded(ACCESS.users, 'Users', <UserDetailPage />)}
        />
        <Route
          path={ROUTES.adminGroups}
          element={guarded(ACCESS.groups, 'Groups', <GroupsPage />)}
        />
        <Route
          path={ROUTES.adminGroup}
          element={guarded(ACCESS.groups, 'Groups', <GroupDetailPage />)}
        />
        <Route
          path={ROUTES.adminRequests}
          element={guarded(ACCESS.requests, 'Access requests', <AdminRequestsPage />)}
        />
        <Route path={ROUTES.adminAudit} element={guarded(ACCESS.audit, 'Audit', <AuditPage />)} />
        <Route
          path={ROUTES.adminTokens}
          element={guarded(ACCESS.tokens, 'Tokens', <AdminTokensPage />)}
        />
        <Route
          path={ROUTES.adminClients}
          element={guarded(ACCESS.clients, 'OAuth clients', <AdminClientsPage />)}
        />
      </Route>
      <Route path="*" element={<Navigate to={ROUTES.home} replace />} />
    </Routes>
  );
}

/** /oauth/consent sits outside ProtectedRoute: it signs in itself and keeps ?txn=. */
function OAuthConsent() {
  const { user, isLoading, signInWithGoogle } = useAuth();
  return (
    <ConsentPage session={{ email: user?.email ?? null, isLoading, signIn: signInWithGoogle }} />
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
