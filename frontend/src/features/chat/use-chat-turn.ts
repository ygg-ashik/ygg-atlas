import { useCallback, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { streamChatMessage } from '@/api/chat-stream';
import type { Provenance } from '@/api/chat';

export interface DraftTurn {
  userText: string;
  assistantText: string;
  toolStatus: string | null;
  notice: string | null; // blocked/error text
  phase: 'thinking' | 'streaming' | null;
  provenance: Provenance[] | null;
}

/**
 * State machine for one in-flight chat turn: shows the user message
 * immediately, accumulates streamed tokens, surfaces tool activity, and on
 * completion swaps the draft for refetched persisted history without a flash.
 */
export function useChatTurn(sessionId: string | null, ensureSession?: () => Promise<string>) {
  const [draft, setDraft] = useState<DraftTurn | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const qc = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (content: string) => {
      if (!content || isStreaming) return;

      // Show the user message immediately, before any async work.
      setDraft({
        userText: content,
        assistantText: '',
        toolStatus: null,
        notice: null,
        phase: 'thinking',
        provenance: null,
      });
      setIsStreaming(true);

      let targetId = sessionId;

      if (!targetId && ensureSession) {
        try {
          targetId = await ensureSession();
        } catch {
          setDraft(
            (d) =>
              d && { ...d, notice: 'Could not start a chat. Please try again.', toolStatus: null, phase: null },
          );
          setIsStreaming(false);
          return;
        }
      }

      if (!targetId) {
        setIsStreaming(false);
        setDraft(null);
        return;
      }

      abortRef.current = new AbortController();
      try {
        await streamChatMessage(
          targetId,
          content,
          (event) => {
            setDraft((d) => {
              if (!d) return d;
              switch (event.type) {
                case 'token':
                  return {
                    ...d,
                    assistantText: d.assistantText + event.content,
                    toolStatus: null,
                    phase: 'streaming' as const,
                  };
                case 'tool_status':
                  return { ...d, toolStatus: event.tool };
                case 'done':
                  return {
                    ...d,
                    assistantText: event.content,
                    toolStatus: null,
                    phase: null,
                    provenance: event.provenance ?? null,
                  };
                case 'blocked':
                  return { ...d, notice: event.reason, toolStatus: null, phase: null };
                case 'error':
                  return { ...d, notice: event.message, toolStatus: null, phase: null };
                default:
                  return d;
              }
            });
          },
          abortRef.current.signal,
        );
      } catch (e) {
        if ((e as DOMException)?.name !== 'AbortError') {
          setDraft(
            (d) => d && { ...d, notice: 'Connection lost. Please try again.', toolStatus: null, phase: null },
          );
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

  return { draft, isStreaming, send, abort };
}
