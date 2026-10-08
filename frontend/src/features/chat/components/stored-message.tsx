import type { ChatMessage } from '@/api/chat';
import { MessageBubble } from './message-bubble';
import { MessageFeedback } from './message-feedback';
import { ProvenanceChips } from './provenance-chips';

export function StoredMessage({ message }: { message: ChatMessage }) {
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
