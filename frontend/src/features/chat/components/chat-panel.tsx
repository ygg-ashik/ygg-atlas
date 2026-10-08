import { useEffect, useMemo, useRef, useState } from 'react';
import { useChatMessages } from '@/api/hooks/use-chat-sessions';
import { useChatTurn } from '../hooks/use-chat-turn';
import { rotatingSuggestions } from '../chat-suggestions';
import { Composer } from './composer';
import { DraftView } from './draft-view';
import { EmptyState } from './empty-state';
import { StoredMessage } from './stored-message';

interface ChatPanelProps {
  sessionId: string | null;
  ensureSession?: () => Promise<string>;
}

export function ChatPanel({ sessionId, ensureSession }: ChatPanelProps) {
  const { data: messages = [] } = useChatMessages(sessionId);
  const { draft, isStreaming, send, abort } = useChatTurn(sessionId, ensureSession);
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  // Stable per chat so starters don't jump around mid-use.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const starters = useMemo(() => rotatingSuggestions(4), [sessionId]);

  useEffect(() => () => abort(), [abort]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, draft?.assistantText, draft?.toolStatus]);

  const canSend = !!(sessionId || ensureSession);

  const sendText = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || isStreaming || !canSend) return;
    setInput('');
    void send(trimmed);
  };

  const isEmpty = messages.length === 0 && !draft;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-4 px-4 pb-6 pt-[84px]">
          {isEmpty && <EmptyState starters={starters} onPick={sendText} />}
          {messages.map((m) => (
            <StoredMessage key={m.id} message={m} />
          ))}
          {draft && <DraftView draft={draft} />}
          <div ref={bottomRef} />
        </div>
      </div>
      <Composer
        value={input}
        onChange={setInput}
        isStreaming={isStreaming}
        canSend={canSend}
        onSubmit={() => sendText(input)}
        onAbort={abort}
      />
    </div>
  );
}
