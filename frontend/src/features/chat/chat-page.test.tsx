import { render, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import ChatPage from './index';

const panelProps = vi.hoisted(() => vi.fn());
vi.mock('./components/chat-panel', () => ({
  ChatPanel: (props: { initialQuestion?: string | null }) => {
    panelProps(props);
    return null;
  },
}));
vi.mock('@/api/hooks/use-chat-sessions', () => ({
  useChatSessions: () => ({ data: [] }),
  useCreateChatSession: () => ({ mutateAsync: vi.fn() }),
}));

let search = '';
function Spy() {
  search = useLocation().search;
  return null;
}

describe('ChatPage ?q= prefill', () => {
  it('hands the question to the panel once and clears the param', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/ask?q=What%20was%20revenue%3F']}>
          <Routes>
            <Route
              path="/ask/:sessionId?"
              element={
                <>
                  <ChatPage />
                  <Spy />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(search).toBe(''));
    expect(panelProps).toHaveBeenCalledWith(
      expect.objectContaining({ initialQuestion: 'What was revenue?' }),
    );
  });
});
