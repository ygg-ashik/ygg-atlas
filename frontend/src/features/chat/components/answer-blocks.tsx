import type { AnswerBlock, ArtifactBlock } from '@/api/chat';
import { ArtifactCard } from './artifact-card';
import { ClarifyBlock } from './clarify-block';

/** What the conversation lets an answer's blocks do. */
export interface BlockActions {
  /** The one answer whose clarify pills are still live (the latest, once settled). */
  activeMessageId: string | null;
  onChoose: (label: string) => void;
  onOpenArtifact: (artifact: ArtifactBlock) => void;
}

interface AnswerBlocksProps {
  messageId: string;
  blocks: AnswerBlock[];
  actions: BlockActions;
}

/** Structured parts of an answer (Track C contract): clarify pills, artifact cards. */
export function AnswerBlocks({ messageId, blocks, actions }: AnswerBlocksProps) {
  return blocks.map((b, i) =>
    b.kind === 'clarify' ? (
      <ClarifyBlock
        key={`clarify-${i}`}
        block={b}
        active={actions.activeMessageId === messageId}
        onChoose={actions.onChoose}
      />
    ) : (
      <ArtifactCard key={b.id} artifact={b} onOpen={() => actions.onOpenArtifact(b)} />
    ),
  );
}
