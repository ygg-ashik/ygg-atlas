import type { ReactNode } from 'react';
import { PresetCard } from '@/ui';
import { CHAT_PRESETS } from '../chat-suggestions';

interface EmptyStateProps {
  /** The centered composer (it glides to the bottom once the chat starts). */
  composer: ReactNode;
  onPick: (question: string) => void;
}

/** First screen of a chat: serif greeting, centered composer, preset gallery. */
export function EmptyState({ composer, onPick }: EmptyStateProps) {
  return (
    <div className="mx-auto max-w-[740px] px-6 pt-[20vh] text-center">
      <h2 className="font-serif text-display font-normal text-ink">What would you like to know?</h2>
      <p className="mt-1.5 text-muted-foreground">
        Ask about revenue, campaigns, accounts or funnels. Every number comes from a governed
        metric.
      </p>
      <div className="mt-8">{composer}</div>
      <div className="mt-8 grid grid-cols-2 gap-3 pb-10 text-left md:grid-cols-4">
        {CHAT_PRESETS.map((p) => (
          <PresetCard
            key={p.title}
            title={p.title}
            description={p.description}
            preview={p.preview}
            compact
            onSelect={() => onPick(p.question)}
          />
        ))}
      </div>
    </div>
  );
}
