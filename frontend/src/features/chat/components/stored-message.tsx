import type { ChatMessage } from '@/api/chat';
import { MessageBubble } from './message-bubble';
import { MessageActions } from './message-actions';
import { ProvenanceChips } from './provenance-chips';

export function StoredMessage({ message }: { message: ChatMessage }) {
  const isAssistant = message.role === 'assistant';
  const provenance = message.provenance ?? [];
  return (
    <div>
      <MessageBubble role={message.role} text={message.content} />
      {isAssistant && provenance.length > 0 && <ProvenanceChips provenance={provenance} />}
      {isAssistant && (
        <MessageActions
          messageId={message.id}
          text={message.content}
          initialRating={message.feedback_rating ?? null}
        />
      )}
    </div>
  );
}
