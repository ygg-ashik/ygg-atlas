// SSE reader for the chat message endpoint. Uses fetch + ReadableStream
// because axios cannot stream response bodies in the browser.
import { auth } from '@/lib/firebase';
import { backendUrl } from './axios-instance';
import type { AnswerBlock, Provenance } from './chat';

export type ChatStreamEvent =
  | { type: 'token'; content: string }
  | { type: 'tool_status'; tool: string }
  | {
      type: 'done';
      content: string;
      provenance: Provenance[];
      blocks?: AnswerBlock[];
      message_id?: string;
      model?: string;
    }
  | { type: 'blocked'; reason: string }
  | { type: 'error'; message: string };

/**
 * Parse a partial SSE buffer into complete events plus the unconsumed
 * remainder. Events are `data: <json>` lines separated by blank lines;
 * malformed lines are skipped.
 */
export function parseSseChunk(buffer: string): {
  events: ChatStreamEvent[];
  remainder: string;
} {
  const events: ChatStreamEvent[] = [];
  const parts = buffer.split('\n\n');
  const remainder = parts.pop() ?? '';
  for (const part of parts) {
    const line = part.trim();
    if (!line.startsWith('data: ')) continue;
    try {
      events.push(JSON.parse(line.slice(6)));
    } catch {
      // malformed line — skip
    }
  }
  return { events, remainder };
}

/**
 * POST a message and stream the SSE response, invoking onEvent per event.
 *
 * NOTE: if `signal` is aborted mid-stream, fetch/reader.read() throws a
 * DOMException with name "AbortError" — callers must catch it and treat it
 * as a cancel, not an error.
 */
export async function streamChatMessage(
  sessionId: string,
  content: string,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const authDisabled = import.meta.env.VITE_AUTH_DISABLED === 'true';
  const user = authDisabled ? null : auth.currentUser;
  const token = user ? await user.getIdToken() : '';
  const resp = await fetch(`${backendUrl}/api/v1/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ content }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    let detail = '';
    try {
      const j = await resp.json();
      detail = j.detail ?? '';
    } catch {
      // non-json error body
    }
    onEvent({ type: 'error', message: detail || `Request failed (${resp.status})` });
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, remainder } = parseSseChunk(buffer);
    buffer = remainder;
    events.forEach(onEvent);
  }
}
