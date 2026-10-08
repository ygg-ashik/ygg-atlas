import type { ChatMessage, Provenance } from '@/api/chat';
import { freshnessLabel, isStale } from '@/lib/freshness';
import type { LastTurn } from '../hooks/use-chat-turn';
import { stepsFromProvenance } from '../steps';
import { AnswerBlocks, type BlockActions } from './answer-blocks';
import { MarkdownMessage } from './markdown-message';
import { UserBubble } from './message-bubble';
import { MessageActions } from './message-actions';
import { Notice } from './notice';
import { ProvenanceChips } from './provenance-chips';
import { StepsBlock } from './steps-block';

/** Warn above the answer when any source behind it is past its freshness SLA. */
function StaleWarning({ provenance }: { provenance: Provenance[] }) {
  const stale = provenance.find((p) => isStale(p.freshness));
  if (!stale) return null;
  return (
    <Notice
      kind="stale"
      message={`${stale.source} last synced ${freshnessLabel(stale.freshness)}`}
    />
  );
}

interface StoredMessageProps {
  message: ChatMessage;
  /** The turn that just finished, so its message keeps the live "Worked for Ns". */
  lastTurn: LastTurn | null;
  blockActions: BlockActions;
}

/** One persisted message: the user's bubble, or the assistant's full answer. */
export function StoredMessage({ message, lastTurn, blockActions }: StoredMessageProps) {
  if (message.role === 'user') return <UserBubble text={message.content} />;

  const provenance = message.provenance ?? [];
  const justFinished = lastTurn?.messageId === message.id ? lastTurn : null;
  return (
    <div className="mb-6">
      <StepsBlock
        steps={justFinished?.steps ?? stepsFromProvenance(provenance)}
        durationMs={justFinished?.durationMs}
      />
      <StaleWarning provenance={provenance} />
      <MarkdownMessage text={message.content} />
      {message.blocks && (
        <AnswerBlocks messageId={message.id} blocks={message.blocks} actions={blockActions} />
      )}
      <ProvenanceChips provenance={provenance} />
      <MessageActions
        messageId={message.id}
        text={message.content}
        initialRating={message.feedback_rating ?? null}
      />
    </div>
  );
}
