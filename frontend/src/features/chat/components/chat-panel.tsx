import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import type { ChatMessage } from '@/api/chat';
import { useChatMessages } from '@/api/hooks/use-chat-sessions';
import { springDefault, withReducedMotion } from '@/ui';
import {
  useChatTurn,
  type DraftTurn,
  type LastTurn,
  type TurnNotice,
} from '../hooks/use-chat-turn';
import { useOpenArtifact } from '../hooks/use-open-artifact';
import { useStickToBottom } from '../hooks/use-stick-to-bottom';
import type { BlockActions } from './answer-blocks';
import { ArtifactSidePanel } from './artifact-side-panel';
import { Composer } from './composer';
import { DraftView } from './draft-view';
import { EmptyState } from './empty-state';
import { Notice } from './notice';
import { StoredMessage } from './stored-message';

interface ChatPanelProps {
  sessionId: string | null;
  ensureSession?: () => Promise<string>;
  /** A `/ask?q=` question to send once, as soon as the panel can send. */
  initialQuestion?: string | null;
}

/** Refetched history lands before the draft clears: never render a turn twice. */
function draftAlreadyPersisted(messages: ChatMessage[], draft: DraftTurn): boolean {
  return draft.messageId !== null && messages.some((m) => m.id === draft.messageId);
}

/** A blocked/errored turn has no message id, but history may still hold its question. */
function historyShowsQuestion(messages: ChatMessage[], draft: DraftTurn): boolean {
  if (draft.phase !== null) return false;
  return messages.slice(-2).some((m) => m.role === 'user' && m.content === draft.userText);
}

/** Clarify pills stay live only on the latest answer, and only once the turn settled. */
function activeAnswerId(messages: ChatMessage[], draft: DraftTurn | null, isStreaming: boolean) {
  if (isStreaming || (draft && !draftAlreadyPersisted(messages, draft))) return null;
  return [...messages].reverse().find((m) => m.role === 'assistant')?.id ?? null;
}

interface ConversationProps {
  messages: ChatMessage[];
  draft: DraftTurn | null;
  notice: TurnNotice | null;
  lastTurn: LastTurn | null;
  onRetry: (text: string) => void;
  blockActions: BlockActions;
}

function Conversation(props: ConversationProps) {
  const { messages, draft, notice, lastTurn, onRetry, blockActions } = props;
  return (
    <div className="mx-auto max-w-[740px] px-6 pb-[190px] pt-[84px]">
      {messages.map((m) => (
        <StoredMessage key={m.id} message={m} lastTurn={lastTurn} blockActions={blockActions} />
      ))}
      {draft && !draftAlreadyPersisted(messages, draft) && (
        <DraftView draft={draft} showUser={!historyShowsQuestion(messages, draft)} />
      )}
      {notice && (
        <Notice
          kind={notice.kind}
          message={notice.message}
          onRetry={notice.kind === 'error' ? () => onRetry(notice.retryText) : undefined}
        />
      )}
    </div>
  );
}

/** Chat layout: empty state with a centered composer, or the conversation with
 * the composer floating at the bottom. The composer glides between the two. */
export function ChatPanel({ sessionId, ensureSession, initialQuestion }: ChatPanelProps) {
  const { data: messages = [] } = useChatMessages(sessionId);
  const { draft, isStreaming, send, abort, notice, lastTurn } = useChatTurn(
    sessionId,
    ensureSession,
  );
  const [input, setInput] = useState('');
  const artifactPanel = useOpenArtifact(sessionId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => () => abort(), [abort]);
  useStickToBottom(scrollRef, [messages.length, draft?.assistantText, draft?.steps.length, notice]);

  const canSend = !!(sessionId || ensureSession);

  // Each distinct prefill is sent once; one arriving mid-stream waits for the turn to end.
  const sentInitial = useRef<string | null>(null);
  useEffect(() => {
    if (!initialQuestion || initialQuestion === sentInitial.current) return;
    if (!canSend || isStreaming) return;
    sentInitial.current = initialQuestion;
    void send(initialQuestion);
  }, [initialQuestion, canSend, isStreaming, send]);
  const sendText = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || isStreaming || !canSend) return;
    setInput('');
    void send(trimmed);
  };
  const isEmpty = messages.length === 0 && !draft && !notice;
  const blockActions: BlockActions = {
    activeMessageId: activeAnswerId(messages, draft, isStreaming),
    onChoose: sendText,
    onOpenArtifact: artifactPanel.open,
  };

  const composer = (
    <motion.div
      layoutId="atlas-composer"
      transition={withReducedMotion(springDefault, reduced)}
      className="flex w-full justify-center"
    >
      <Composer
        value={input}
        onChange={setInput}
        onSend={() => sendText(input)}
        onStop={abort}
        isStreaming={isStreaming}
        disabled={!canSend}
        startedAt={draft?.startedAt}
      />
    </motion.div>
  );

  return (
    <div className="absolute inset-0 flex">
      <div className="relative min-w-0 flex-1">
        <div ref={scrollRef} className="absolute inset-0 overflow-y-auto">
          {isEmpty ? (
            <EmptyState composer={composer} onPick={sendText} />
          ) : (
            <Conversation
              messages={messages}
              draft={draft}
              notice={notice}
              lastTurn={lastTurn}
              onRetry={sendText}
              blockActions={blockActions}
            />
          )}
        </div>
        {!isEmpty && (
          <>
            <div
              aria-hidden
              className="scroll-edge-bottom pointer-events-none absolute inset-x-0 bottom-0 z-[5] h-[130px]"
            />
            <div className="absolute inset-x-0 bottom-4 z-10 px-6">{composer}</div>
          </>
        )}
      </div>
      <ArtifactSidePanel artifact={artifactPanel.artifact} onClose={artifactPanel.close} />
    </div>
  );
}
