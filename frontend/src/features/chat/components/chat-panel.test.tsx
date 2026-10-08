import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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

const artifactBlock = {
  kind: 'artifact',
  id: 'x',
  artifact_type: 'breakdown',
  title: 'Revenue: breakdown',
  unit: 'AED',
  columns: ['Label', 'Value'],
  rows: [['b2b', 1000]],
  provenance: { tool: 'metric_breakdown', source: 'demo', executed_at: 't' },
};

function answerWithBlocks(id: string, blocks: unknown[]) {
  return {
    id,
    role: 'assistant',
    content: 'Here is the split.',
    created_at: '',
    provenance: [],
    blocks,
  };
}

const clarifyBlock = {
  kind: 'clarify',
  question: 'Which period?',
  options: [{ label: 'Last 7 days' }, { label: 'Last 30 days' }],
};

/** Pin the panel's 1200px breakpoint (happy-dom's default viewport is 1024px wide). */
function stubViewport(wide: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: wide,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
}

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

  describe('answer blocks', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('renders clarify pills and opens an artifact in the side panel', async () => {
      stubViewport(true);
      turn.messages = [
        { id: 'u1', role: 'user', content: 'split revenue', created_at: '' },
        answerWithBlocks('a1', [clarifyBlock, artifactBlock]),
      ];
      renderPanel();
      await userEvent.click(screen.getByRole('button', { name: 'Last 7 days' }));
      expect(send).toHaveBeenCalledWith('Last 7 days');
      await userEvent.click(screen.getByRole('button', { name: /Revenue: breakdown/ }));
      expect(
        await screen.findByRole('heading', { name: 'Revenue: breakdown' }),
      ).toBeInTheDocument();
      expect(screen.getByRole('complementary', { name: 'Artifact' })).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Close artifact' }));
      await waitFor(() =>
        expect(
          screen.queryByRole('heading', { name: 'Revenue: breakdown' }),
        ).not.toBeInTheDocument(),
      );
    });

    it('only the latest answer keeps live clarify pills', () => {
      turn.messages = [
        answerWithBlocks('a1', [clarifyBlock]),
        { id: 'u2', role: 'user', content: 'something else', created_at: '' },
        answerWithBlocks('a2', []),
      ];
      renderPanel();
      expect(screen.getByRole('button', { name: 'Last 7 days' })).toBeDisabled();
    });

    it('below 1200px the artifact opens as an overlay sheet', async () => {
      stubViewport(false);
      turn.messages = [answerWithBlocks('a1', [artifactBlock])];
      renderPanel();
      await userEvent.click(screen.getByRole('button', { name: /Revenue: breakdown/ }));
      const sheet = await screen.findByRole('dialog', { name: 'Artifact' });
      expect(sheet).toContainElement(screen.getByRole('heading', { name: 'Revenue: breakdown' }));
    });
  });
});
