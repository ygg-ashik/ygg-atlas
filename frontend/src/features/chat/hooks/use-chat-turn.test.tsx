import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChatStreamEvent } from '@/api/chat-stream';
import { useChatTurn } from './use-chat-turn';

const streamMock = vi.hoisted(() => vi.fn());
vi.mock('@/api/chat-stream', () => ({
  streamChatMessage: streamMock,
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Deferred stream: the test emits events and finishes the "connection". */
function deferredStream() {
  let emit!: (e: ChatStreamEvent) => void;
  let finish!: () => void;
  streamMock.mockImplementation(
    (_id: string, _content: string, onEvent: (e: ChatStreamEvent) => void) => {
      emit = onEvent;
      return new Promise<void>((resolve) => {
        finish = resolve;
      });
    },
  );
  return { emit: (e: ChatStreamEvent) => emit(e), finish: () => finish() };
}

describe('useChatTurn', () => {
  beforeEach(() => {
    streamMock.mockReset();
  });

  it('walks thinking → tool_status → streaming → done → cleared', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });

    expect(result.current.draft).toBeNull();
    expect(result.current.isStreaming).toBe(false);

    act(() => {
      void result.current.send('What was revenue last week?');
    });

    // User message is visible immediately, in "thinking" phase.
    await waitFor(() => expect(result.current.isStreaming).toBe(true));
    expect(result.current.draft).toMatchObject({
      userText: 'What was revenue last week?',
      assistantText: '',
      phase: 'thinking',
    });

    // Tool status surfaces while the agent consults the atlas.
    act(() => stream.emit({ type: 'tool_status', tool: 'query_metric' }));
    expect(result.current.draft?.toolStatus).toBe('query_metric');

    // Tokens accumulate and clear the tool status.
    act(() => stream.emit({ type: 'token', content: 'Revenue was ' }));
    act(() => stream.emit({ type: 'token', content: 'AED 1.2M.' }));
    expect(result.current.draft).toMatchObject({
      assistantText: 'Revenue was AED 1.2M.',
      toolStatus: null,
      phase: 'streaming',
    });

    // Done replaces the text and attaches provenance.
    const provenance = [
      {
        tool: 'query_metric',
        metric_id: 'revenue_total',
        metric_name: 'Total revenue',
        source: 'orders_db',
        freshness: '2h ago',
        executed_at: '2026-09-23T10:00:00Z',
      },
    ];
    act(() => stream.emit({ type: 'done', content: 'Revenue was AED 1,200,000.', provenance }));
    expect(result.current.draft).toMatchObject({
      assistantText: 'Revenue was AED 1,200,000.',
      phase: null,
      provenance,
    });

    // Stream closes → draft cleared after history refetch.
    act(() => stream.finish());
    await waitFor(() => expect(result.current.isStreaming).toBe(false));
    await waitFor(() => expect(result.current.draft).toBeNull());
  });

  it('surfaces blocked events as a notice', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });

    act(() => {
      void result.current.send('DROP TABLE orders');
    });
    await waitFor(() => expect(result.current.isStreaming).toBe(true));

    act(() => stream.emit({ type: 'blocked', reason: 'This request is outside the atlas scope.' }));
    expect(result.current.draft?.notice).toBe('This request is outside the atlas scope.');
    expect(result.current.draft?.phase).toBeNull();

    act(() => stream.finish());
    await waitFor(() => expect(result.current.isStreaming).toBe(false));
  });

  it('creates a session on first send via ensureSession', async () => {
    streamMock.mockResolvedValue(undefined);
    const ensureSession = vi.fn().mockResolvedValue('new-sess');
    const { result } = renderHook(() => useChatTurn(null, ensureSession), { wrapper });

    await act(async () => {
      await result.current.send('hello');
    });

    expect(ensureSession).toHaveBeenCalledTimes(1);
    expect(streamMock).toHaveBeenCalledWith(
      'new-sess',
      'hello',
      expect.any(Function),
      expect.any(AbortSignal),
    );
  });

  it('shows a notice when session creation fails', async () => {
    const ensureSession = vi.fn().mockRejectedValue(new Error('nope'));
    const { result } = renderHook(() => useChatTurn(null, ensureSession), { wrapper });

    await act(async () => {
      await result.current.send('hello');
    });

    expect(streamMock).not.toHaveBeenCalled();
    expect(result.current.draft?.notice).toBe('Could not start a chat. Please try again.');
  });

  it('ignores sends while a stream is in flight', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });

    act(() => {
      void result.current.send('first');
    });
    await waitFor(() => expect(result.current.isStreaming).toBe(true));

    await act(async () => {
      await result.current.send('second');
    });
    expect(streamMock).toHaveBeenCalledTimes(1);
    expect(result.current.draft?.userText).toBe('first');

    act(() => stream.finish());
    await waitFor(() => expect(result.current.isStreaming).toBe(false));
  });

  it('records steps from tool_status and completes them on tokens', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });
    act(() => void result.current.send('q'));
    await waitFor(() => expect(result.current.isStreaming).toBe(true));
    expect(typeof result.current.draft?.startedAt).toBe('number');

    act(() => stream.emit({ type: 'tool_status', tool: 'search_atlas' }));
    act(() => stream.emit({ type: 'tool_status', tool: 'query_metric' }));
    expect(result.current.draft?.steps).toEqual([
      { tool: 'search_atlas', status: 'done' },
      { tool: 'query_metric', status: 'running' },
    ]);
    act(() => stream.emit({ type: 'token', content: 'Revenue' }));
    expect(result.current.draft?.steps.every((s) => s.status === 'done')).toBe(true);
    act(() => stream.finish());
    await waitFor(() => expect(result.current.isStreaming).toBe(false));
  });

  it('keeps lastTurn (steps + duration) for the persisted message after done', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });
    act(() => void result.current.send('q'));
    await waitFor(() => expect(result.current.isStreaming).toBe(true));
    act(() => stream.emit({ type: 'tool_status', tool: 'query_metric' }));
    act(() => stream.emit({ type: 'done', content: 'ok', provenance: [], message_id: 'm-9' }));
    act(() => stream.finish());
    await waitFor(() => expect(result.current.draft).toBeNull());
    expect(result.current.lastTurn).toMatchObject({
      messageId: 'm-9',
      steps: [{ tool: 'query_metric', status: 'done' }],
    });
    expect(result.current.lastTurn?.durationMs).toBeGreaterThanOrEqual(0);
  });

  it('keeps an error notice with retry text after the draft clears', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });
    act(() => void result.current.send('why did revenue drop?'));
    await waitFor(() => expect(result.current.isStreaming).toBe(true));
    act(() => stream.emit({ type: 'error', message: 'Something went wrong.' }));
    act(() => stream.finish());
    await waitFor(() => expect(result.current.draft).toBeNull());
    expect(result.current.notice).toEqual({
      kind: 'error',
      message: 'Something went wrong.',
      retryText: 'why did revenue drop?',
    });
  });

  it('clears the notice on the next send', async () => {
    const stream = deferredStream();
    const { result } = renderHook(() => useChatTurn('sess-1'), { wrapper });
    act(() => void result.current.send('a'));
    await waitFor(() => expect(result.current.isStreaming).toBe(true));
    act(() => stream.emit({ type: 'blocked', reason: 'Daily limit reached.' }));
    act(() => stream.finish());
    await waitFor(() => expect(result.current.notice?.kind).toBe('blocked'));
    deferredStream();
    act(() => void result.current.send('b'));
    expect(result.current.notice).toBeNull();
  });
});
