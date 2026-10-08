// src/features/chat/components/chat-thread-list.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ChatThreadList } from './chat-thread-list';

vi.mock('@/api/hooks/use-chat-sessions', () => ({
  useChatSessions: () => ({
    data: [
      {
        id: 's1',
        title: 'Q3 revenue review',
        created_at: '',
        updated_at: new Date().toISOString(),
      },
      { id: 's2', title: 'ROAS by channel', created_at: '', updated_at: new Date().toISOString() },
    ],
  }),
  useDeleteChatSession: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <ChatThreadList />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ChatThreadList', () => {
  it('lists sessions and marks the one in the URL as current', () => {
    renderAt('/ask/s2');
    expect(screen.getByText('Q3 revenue review')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /ROAS by channel/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('navigates to a thread and to a new chat', async () => {
    renderAt('/ask');
    await userEvent.click(screen.getByRole('link', { name: /Q3 revenue review/ }));
    expect(screen.getByTestId('where')).toHaveTextContent('/ask/s1');
    await userEvent.click(screen.getByRole('button', { name: /new chat/i }));
    expect(screen.getByTestId('where')).toHaveTextContent('/ask');
  });
});
