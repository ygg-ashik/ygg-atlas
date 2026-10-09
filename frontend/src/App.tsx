import { useMemo } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/api/query-client';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { ThemeProvider } from '@/lib/theme-provider';
import { Toaster } from '@/ui';
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
  AdminRequestsPage,
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

/** Home route: the Overview dashboard, greeted by the signed-in user's name. */
function Home() {
  const { user } = useAuth();
  return <OverviewPage userName={user?.name ?? ''} />;
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
