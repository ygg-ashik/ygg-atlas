import type { DraftTurn } from '../hooks/use-chat-turn';
import { MarkdownMessage } from './markdown-message';
import { UserBubble } from './message-bubble';
import { ProvenanceChips } from './provenance-chips';
import { StepsBlock } from './steps-block';

interface DraftViewProps {
  draft: DraftTurn;
  /** False once refetched history already shows the question (no double bubble). */
  showUser: boolean;
}

/** The in-flight turn: live steps, then streamed prose with blur-in, then chips. */
export function DraftView({ draft, showUser }: DraftViewProps) {
  const working = draft.phase !== null;
  return (
    <>
      {showUser && <UserBubble text={draft.userText} />}
      <StepsBlock steps={draft.steps} live={working} durationMs={draft.durationMs ?? undefined} />
      {draft.phase === 'thinking' && draft.steps.length === 0 && (
        <p className="mb-3 text-label text-muted-foreground">Thinking…</p>
      )}
      {draft.assistantText && (
        <MarkdownMessage text={draft.assistantText} streaming={draft.phase === 'streaming'} />
      )}
      <ProvenanceChips provenance={draft.provenance ?? []} />
    </>
  );
}
