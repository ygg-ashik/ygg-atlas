import { useCallback, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { streamChatMessage, type ChatStreamEvent } from '@/api/chat-stream';
import type { Provenance } from '@/api/chat';
import { applyToolStatus, completeAll, type Step } from '../steps';

export interface DraftTurn {
  userText: string;
  assistantText: string;
  toolStatus: string | null;
  notice: string | null; // blocked/error text (kept for compatibility)
  phase: 'thinking' | 'streaming' | null;
  provenance: Provenance[] | null;
  steps: Step[];
  startedAt: number;
}

/** A blocked/error outcome that outlives the draft so the reader can retry. */
export interface TurnNotice {
  kind: 'blocked' | 'error';
  message: string;
  retryText: string;
}

/** Steps + timing of the turn that just finished, keyed to its persisted message. */
export interface LastTurn {
  messageId: string;
  steps: Step[];
  durationMs: number;
}

/** Steps after an event: tool_status starts a step, prose or done completes them. */
function nextSteps(steps: Step[], event: ChatStreamEvent): Step[] {
  if (event.type === 'tool_status') return applyToolStatus(steps, event.tool);
  if (event.type === 'token' || event.type === 'done') return completeAll(steps);
  return steps;
}

/** Pure draft transition for one stream event (steps are computed by the caller). */
function reduceDraft(d: DraftTurn, event: ChatStreamEvent, steps: Step[]): DraftTurn {
  switch (event.type) {
    case 'token':
      return {
        ...d,
        assistantText: d.assistantText + event.content,
        toolStatus: null,
        phase: 'streaming',
        steps,
      };
    case 'tool_status':
      return { ...d, toolStatus: event.tool, steps };
    case 'done':
      return {
        ...d,
        assistantText: event.content,
        toolStatus: null,
        phase: null,
        provenance: event.provenance ?? null,
        steps,
      };
    case 'blocked':
      return { ...d, notice: event.reason, toolStatus: null, phase: null };
    case 'error':
      return { ...d, notice: event.message, toolStatus: null, phase: null };
    default:
      return d;
  }
}

function failDraft(message: string) {
  return (d: DraftTurn | null) => d && { ...d, notice: message, toolStatus: null, phase: null };
}

/**
 * State machine for one in-flight chat turn: shows the user message
 * immediately, accumulates streamed tokens, tracks the steps the agent takes,
 * and on completion swaps the draft for refetched persisted history without a
 * flash. Blocked/error outcomes persist as `notice` until the next send.
 */
export function useChatTurn(sessionId: string | null, ensureSession?: () => Promise<string>) {
  const [draft, setDraft] = useState<DraftTurn | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [notice, setNotice] = useState<TurnNotice | null>(null);
  const [lastTurn, setLastTurn] = useState<LastTurn | null>(null);
  const qc = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (content: string) => {
      if (!content || isStreaming) return;
      setNotice(null);
      const raise = (kind: TurnNotice['kind'], message: string) =>
        setNotice({ kind, message, retryText: content });

      // Show the user message immediately, before any async work.
      const startedAt = Date.now();
      let steps: Step[] = [];
      setDraft({
        userText: content,
        assistantText: '',
        toolStatus: null,
        notice: null,
        phase: 'thinking',
        provenance: null,
        steps,
        startedAt,
      });
      setIsStreaming(true);

      let targetId = sessionId;

      if (!targetId && ensureSession) {
        try {
          targetId = await ensureSession();
        } catch {
          const message = 'Could not start a chat. Please try again.';
          setDraft(failDraft(message));
          raise('error', message);
          setIsStreaming(false);
          return;
        }
      }

      if (!targetId) {
        setIsStreaming(false);
        setDraft(null);
        return;
      }

      // Side effects stay out of the state updater (StrictMode replays updaters).
      const onEvent = (event: ChatStreamEvent) => {
        steps = nextSteps(steps, event);
        const current = steps;
        setDraft((d) => d && reduceDraft(d, event, current));
        if (event.type === 'done' && event.message_id) {
          setLastTurn({
            messageId: event.message_id,
            steps: current,
            durationMs: Date.now() - startedAt,
          });
        }
        if (event.type === 'blocked') raise('blocked', event.reason);
        if (event.type === 'error') raise('error', event.message);
      };

      abortRef.current = new AbortController();
      try {
        await streamChatMessage(targetId, content, onEvent, abortRef.current.signal);
      } catch (e) {
        if ((e as DOMException)?.name !== 'AbortError') {
          const message = 'Connection lost. Please try again.';
          setDraft(failDraft(message));
          raise('error', message);
        }
      } finally {
        setIsStreaming(false);
        // Refetch persisted history; keep the draft visible until the refetch
        // lands so there is no blank flash between stream end and query data.
        await Promise.all([
          qc.refetchQueries({ queryKey: ['chat-messages', targetId] }),
          qc.invalidateQueries({ queryKey: ['chat-sessions'] }),
        ]);
        setDraft(null);
      }
    },
    [sessionId, ensureSession, isStreaming, qc],
  );

  const abort = useCallback(() => abortRef.current?.abort(), []);

  return { draft, isStreaming, send, abort, notice, lastTurn };
}
