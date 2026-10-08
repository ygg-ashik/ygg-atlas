import { useState } from 'react';
import type { ClarifyBlock as ClarifyBlockData } from '@/api/chat';
import { Button } from '@/ui';

interface ClarifyBlockProps {
  block: ClarifyBlockData;
  /** Only the latest answer's clarification is actionable. */
  active: boolean;
  onChoose: (label: string) => void;
}

/** Clarify instead of guess (guardrail #1): choice pills (DESIGN.md › Clarify). */
export function ClarifyBlock({ block, active, onChoose }: ClarifyBlockProps) {
  const [chosen, setChosen] = useState<string | null>(null);
  return (
    <div role="group" aria-label={block.question} className="my-2.5 flex flex-wrap gap-2">
      {block.options.map((o) => (
        <Button
          key={o.label}
          variant="pill"
          size="sm"
          // The chosen pill stays at full strength after the others go inert.
          className="data-[selected=true]:disabled:opacity-100"
          data-selected={chosen === o.label}
          disabled={!active || chosen !== null}
          onClick={() => {
            setChosen(o.label);
            onChoose(o.label);
          }}
        >
          {o.label}
        </Button>
      ))}
    </div>
  );
}
