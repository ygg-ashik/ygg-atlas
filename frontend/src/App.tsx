import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { LayoutDashboard, Library, MessageCircle } from 'lucide-react';
import { queryClient } from '@/api/query-client';
import { ThemeProvider } from '@/lib/theme-provider';
import { Toaster } from '@/ui';
import { AuthProvider, LoginPage, ProtectedRoute, useAuth } from '@/features/auth';
import { Shell, type NavItem } from '@/features/layout';
import ChatPage, { ChatThreadList } from '@/features/chat';
import { MetricsPage } from '@/features/metrics';
import { CommandPalette, CommandTrigger } from '@/features/command';
import { OverviewPage } from '@/features/dashboard';

const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/ask', label: 'Ask Atlas', icon: MessageCircle },
  { to: '/metrics', label: 'Metrics', icon: Library },
];

/** Composition point: wires auth, chat and the command palette into the layout so features stay decoupled. */
function AppShell() {
  const { user, signOut } = useAuth();
  return (
    <Shell
      user={user}
      onSignOut={() => void signOut()}
      nav={NAV}
      threads={
        <>
          <CommandTrigger />
          <ChatThreadList />
        </>
      }
    >
      <Outlet />
      <CommandPalette />
    </Shell>
  );
}

/** Home route: the Overview dashboard, greeted by the signed-in user's name. */
function Home() {
  const { user } = useAuth();
  return <OverviewPage userName={user?.name ?? ''} />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="system">
        <AuthProvider>
          <BrowserRouter>
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
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
          <Toaster />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
