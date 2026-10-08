import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatPanel } from './chat-panel';

const send = vi.hoisted(() => vi.fn());
const turn = vi.hoisted(() => ({ draft: null as unknown, messages: [] as unknown[] }));
vi.mock('../hooks/use-chat-turn', () => ({
  useChatTurn: () => ({
    draft: turn.draft,
    isStreaming: false,
    send,
    abort: vi.fn(),
    notice: null,
    lastTurn: null,
  }),
}));
vi.mock('@/api/hooks/use-chat-sessions', () => ({
  useChatMessages: () => ({ data: turn.messages }),
}));
// The api client boots Firebase on import; the panel never talks to the network here.
vi.mock('@/api/chat', () => ({ setMessageFeedback: vi.fn() }));

function renderPanel(initialQuestion?: string) {
  const qc = new QueryClient();
  const ui = (
    <QueryClientProvider client={qc}>
      <ChatPanel
        sessionId={null}
        ensureSession={async () => 's1'}
        initialQuestion={initialQuestion}
      />
    </QueryClientProvider>
  );
  const result = render(ui);
  return { ...result, rerenderSame: () => result.rerender(ui) };
}

describe('ChatPanel', () => {
  beforeEach(() => {
    send.mockReset();
    turn.draft = null;
    turn.messages = [];
  });

  it('sends a ?q= question exactly once', () => {
    const { rerenderSame } = renderPanel('What was revenue?');
    rerenderSame();
    expect(send).toHaveBeenCalledOnce();
    expect(send).toHaveBeenCalledWith('What was revenue?');
  });

  it('empty state: serif greeting, preset gallery, centered composer', async () => {
    renderPanel();
    expect(screen.getByRole('heading', { name: 'What would you like to know?' })).toHaveClass(
      'font-serif',
    );
    await userEvent.click(screen.getByRole('button', { name: /Revenue review/ }));
    expect(send).toHaveBeenCalledWith('What was revenue last week?');
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  it('drops the finished draft once history holds its message (no double answer)', () => {
    turn.messages = [
      { id: 'u1', role: 'user', content: 'q', created_at: 't' },
      { id: 'm1', role: 'assistant', content: 'Revenue was 42', provenance: [], created_at: 't' },
    ];
    turn.draft = {
      userText: 'q',
      assistantText: 'Revenue was 42',
      toolStatus: null,
      notice: null,
      phase: null,
      provenance: [],
      steps: [{ tool: 'query_metric', status: 'done' }],
      startedAt: 0,
      messageId: 'm1',
      durationMs: 4200,
    };
    renderPanel();
    expect(screen.getAllByText('Revenue was 42')).toHaveLength(1);
    expect(screen.getAllByText('q')).toHaveLength(1);
  });
});
