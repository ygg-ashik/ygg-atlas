import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import ChatPage from './index';

const mutateAsync = vi.fn(() => Promise.resolve({ id: 'new1' }));

vi.mock('@/api/hooks/use-chat-sessions', () => ({
  useChatSessions: () => ({ data: [{ id: 's1', title: 'Q3 revenue review' }] }),
  useCreateChatSession: () => ({ mutateAsync }),
  useDeleteChatSession: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

// The panel is covered by its own tests; here it only exposes the props ChatPage passes.
vi.mock('./components/chat-panel', () => ({
  ChatPanel: ({
    sessionId,
    ensureSession,
  }: {
    sessionId: string | null;
    ensureSession?: () => Promise<string>;
  }) => (
    <div>
      <p data-testid="session">{sessionId ?? 'draft'}</p>
      {ensureSession && (
        <button type="button" onClick={() => void ensureSession()}>
          send
        </button>
      )}
    </div>
  ),
}));

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/ask/:sessionId?"
          element={
            <>
              <ChatPage />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ChatPage', () => {
  it('shows the thread from the URL in the toolbar', () => {
    renderAt('/ask/s1');
    expect(screen.getByRole('heading', { name: 'Q3 revenue review' })).toBeInTheDocument();
    expect(screen.getByTestId('session')).toHaveTextContent('s1');
    expect(screen.queryByRole('button', { name: 'send' })).toBeNull();
  });

  it('starts as a draft and moves to /ask/<id> once the session exists', async () => {
    renderAt('/ask');
    expect(screen.getByRole('heading', { name: 'New chat' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'send' }));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/ask/new1'));
    expect(screen.getByTestId('session')).toHaveTextContent('new1');
    expect(mutateAsync).toHaveBeenCalledOnce();
  });
});
