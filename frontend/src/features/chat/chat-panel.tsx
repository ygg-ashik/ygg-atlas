import { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, Orbit, SendHorizontal, Square } from 'lucide-react';
import { useChatMessages } from '@/api/hooks/use-chat-sessions';
import { type ChatMessage } from '@/api/chat';
import { useChatTurn, type DraftTurn } from './use-chat-turn';
import { MarkdownMessage } from './markdown-message';
import { stabilizeStreamingMarkdown } from './markdown-stream';
import { ProvenanceChips } from './provenance-chips';
import { MessageFeedback } from './message-feedback';
import { rotatingSuggestions } from './chat-suggestions';

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
        <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-6">
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

function EmptyState({ starters, onPick }: { starters: string[]; onPick: (text: string) => void }) {
  return (
    <div className="mt-16 text-center">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-accent-foreground">
        <Orbit className="h-6 w-6" />
      </div>
      <h2 className="text-lg font-semibold tracking-tight">Ask the atlas</h2>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
        Revenue, orders, funnels, campaigns — answered from governed metric definitions. Every
        number carries provenance.
      </p>
      <div className="mx-auto mt-6 grid max-w-lg gap-2 sm:grid-cols-2">
        {starters.map((starter) => (
          <button
            key={starter}
            type="button"
            onClick={() => onPick(starter)}
            className="rounded-lg border bg-card px-3 py-2.5 text-left text-xs text-muted-foreground shadow-sm transition-colors hover:border-primary/40 hover:text-foreground"
          >
            {starter}
          </button>
        ))}
      </div>
    </div>
  );
}

function StoredMessage({ message }: { message: ChatMessage }) {
  const isAssistant = message.role === 'assistant';
  const provenance = message.provenance ?? [];
  return (
    <div>
      <MessageBubble role={message.role} text={message.content} />
      {isAssistant && provenance.length > 0 && <ProvenanceChips provenance={provenance} />}
      {isAssistant && (
        <MessageFeedback messageId={message.id} initialRating={message.feedback_rating ?? null} />
      )}
    </div>
  );
}

function DraftView({ draft }: { draft: DraftTurn }) {
  const provenance = draft.provenance ?? [];
  const assistantText =
    draft.phase === 'streaming'
      ? stabilizeStreamingMarkdown(draft.assistantText)
      : draft.assistantText;
  return (
    <>
      <MessageBubble role="user" text={draft.userText} />
      {draft.phase === 'thinking' && !draft.toolStatus && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
          Thinking…
        </div>
      )}
      {draft.assistantText && <MessageBubble role="assistant" text={assistantText} />}
      {provenance.length > 0 && <ProvenanceChips provenance={provenance} />}
      {draft.toolStatus && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin text-primary" />
          Consulting atlas: <code className="rounded bg-secondary px-1">{draft.toolStatus}</code>…
        </div>
      )}
      {draft.notice && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
          {draft.notice}
        </div>
      )}
    </>
  );
}

function Composer({
  value,
  onChange,
  isStreaming,
  canSend,
  onSubmit,
  onAbort,
}: {
  value: string;
  onChange: (value: string) => void;
  isStreaming: boolean;
  canSend: boolean;
  onSubmit: () => void;
  onAbort: () => void;
}) {
  return (
    <div className="border-t bg-background">
      <div className="mx-auto w-full max-w-3xl px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea
            className="max-h-32 min-h-[42px] flex-1 resize-none rounded-lg border bg-background px-3 py-2.5 text-sm shadow-sm outline-none transition-shadow placeholder:text-muted-foreground focus:ring-1 focus:ring-ring disabled:opacity-50"
            rows={1}
            placeholder="Ask about revenue, orders, funnels…"
            value={value}
            disabled={isStreaming || !canSend}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                onSubmit();
              }
            }}
          />
          {isStreaming ? (
            <button
              type="button"
              aria-label="Stop generating"
              className="rounded-lg bg-muted p-2.5 text-muted-foreground transition-colors hover:bg-muted/80"
              onClick={onAbort}
            >
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="button"
              aria-label="Send"
              className="rounded-lg bg-primary p-2.5 text-primary-foreground transition-opacity disabled:opacity-50"
              disabled={!value.trim() || !canSend}
              onClick={onSubmit}
            >
              <SendHorizontal className="h-4 w-4" />
            </button>
          )}
        </div>
        <p className="px-1 pt-1.5 text-[10px] text-muted-foreground">
          Answers come from vetted atlas metrics — check the provenance chips under each number.
        </p>
      </div>
    </div>
  );
}

function MessageBubble({ role, text }: { role: 'user' | 'assistant'; text: string }) {
  return (
    <div className={role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
      <div
        className={
          role === 'user'
            ? 'max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-sm text-primary-foreground'
            : // Assistant answers carry tables/lists: the bubble hugs its content
              // (w-fit) but may use the full row (max-w-full min-w-0) so wide
              // markdown scrolls INSIDE the background instead of bleeding out.
              'w-fit min-w-0 max-w-full rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2 text-sm'
        }
      >
        {role === 'assistant' ? <MarkdownMessage text={text} /> : text}
      </div>
    </div>
  );
}
