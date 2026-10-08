import { Loader2 } from 'lucide-react';
import type { DraftTurn } from '../hooks/use-chat-turn';
import { MessageBubble } from './message-bubble';
import { ProvenanceChips } from './provenance-chips';

export function DraftView({ draft }: { draft: DraftTurn }) {
  const provenance = draft.provenance ?? [];
  return (
    <>
      <MessageBubble role="user" text={draft.userText} />
      {draft.phase === 'thinking' && !draft.toolStatus && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
          Thinking…
        </div>
      )}
      {draft.assistantText && <MessageBubble role="assistant" text={draft.assistantText} />}
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
