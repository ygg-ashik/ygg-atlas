import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { MessageCircle } from 'lucide-react';
import { queryClient } from '@/api/query-client';
import { ThemeProvider } from '@/lib/theme-provider';
import { Toaster } from '@/ui';
import { AuthProvider, LoginPage, ProtectedRoute, useAuth } from '@/features/auth';
import { Shell, type NavItem } from '@/features/layout';
import ChatPage, { ChatThreadList } from '@/features/chat';

// Tracks D1/E-fe append their entries here (Metrics, Overview).
const NAV: NavItem[] = [{ to: '/ask', label: 'Ask Atlas', icon: MessageCircle }];

/** Composition point: wires auth + chat into the layout so features stay decoupled. */
function AppShell() {
  const { user, signOut } = useAuth();
  return (
    <Shell user={user} onSignOut={() => void signOut()} nav={NAV} threads={<ChatThreadList />}>
      <Outlet />
    </Shell>
  );
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
                <Route index element={<Navigate to="/ask" replace />} />
                <Route path="ask/:sessionId?" element={<ChatPage />} />
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
