import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseSseChunk, streamChatMessage, type ChatStreamEvent } from './chat-stream';

vi.mock('@/lib/firebase', () => ({
  auth: { currentUser: { getIdToken: async () => 'test-token' } },
}));

describe('parseSseChunk', () => {
  it('parses complete events and keeps the remainder', () => {
    const buffer =
      'data: {"type":"token","content":"Hello"}\n\n' +
      'data: {"type":"tool_status","tool":"query_metric"}\n\n' +
      'data: {"type":"token","content":" wor';
    const { events, remainder } = parseSseChunk(buffer);
    expect(events).toEqual([
      { type: 'token', content: 'Hello' },
      { type: 'tool_status', tool: 'query_metric' },
    ]);
    expect(remainder).toBe('data: {"type":"token","content":" wor');
  });

  it('skips malformed json and non-data lines', () => {
    const buffer = 'data: {not json}\n\n: comment\n\ndata: {"type":"token","content":"ok"}\n\n';
    const { events, remainder } = parseSseChunk(buffer);
    expect(events).toEqual([{ type: 'token', content: 'ok' }]);
    expect(remainder).toBe('');
  });

  it('parses a done event with provenance', () => {
    const done = {
      type: 'done',
      content: 'Revenue was AED 1.2M.',
      provenance: [
        {
          tool: 'query_metric',
          metric_id: 'revenue_total',
          metric_name: 'Total revenue',
          source: 'orders_db',
          freshness: '2h ago',
          executed_at: '2026-09-23T10:00:00Z',
        },
      ],
      model: 'claude',
    };
    const { events } = parseSseChunk(`data: ${JSON.stringify(done)}\n\n`);
    expect(events).toEqual([done]);
  });

  it('returns an empty result for an empty buffer', () => {
    expect(parseSseChunk('')).toEqual({ events: [], remainder: '' });
  });
});

describe('streamChatMessage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const sseBody = (chunks: string[]) =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });

  it('delivers events across chunk boundaries with auth header', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(
          sseBody([
            'data: {"type":"token","content":"Rev"}\n\ndata: {"type":"tok',
            'en","content":"enue"}\n\n',
            'data: {"type":"done","content":"Revenue","provenance":[]}\n\n',
          ]),
          { status: 200 },
        ),
      );
    vi.stubGlobal('fetch', fetchMock);

    const events: ChatStreamEvent[] = [];
    await streamChatMessage('sess-1', 'What was revenue?', (e) => events.push(e));

    expect(events).toEqual([
      { type: 'token', content: 'Rev' },
      { type: 'token', content: 'enue' },
      { type: 'done', content: 'Revenue', provenance: [] },
    ]);

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toContain('/api/v1/chat/sessions/sess-1/messages');
    expect(init.headers.Authorization).toBe('Bearer test-token');
    expect(JSON.parse(init.body)).toEqual({ content: 'What was revenue?' });
  });

  it('emits an error event on a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: 'Session not found' }), { status: 404 }),
        ),
    );

    const events: ChatStreamEvent[] = [];
    await streamChatMessage('missing', 'hi', (e) => events.push(e));
    expect(events).toEqual([{ type: 'error', message: 'Session not found' }]);
  });
});
