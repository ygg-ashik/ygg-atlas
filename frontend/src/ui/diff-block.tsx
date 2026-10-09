// src/ui/diff-block.tsx
import { cn } from './utils';

export type DiffKind = 'add' | 'remove' | 'context';

export interface DiffLine {
  kind: DiffKind;
  text: string;
}

const LINE: Record<DiffKind, string> = {
  add: 'text-positive',
  remove: 'text-negative line-through decoration-1',
  context: 'text-muted-foreground',
};
const MARK: Record<DiffKind, string> = { add: '+ ', remove: '− ', context: '  ' };
const SPOKEN: Record<DiffKind, string> = { add: 'added: ', remove: 'removed: ', context: '' };

/** Mono before → after diff (DESIGN.md › diff-block): + positive, − negative and
 * struck through. The marks are visible text so colour is never the only signal. */
export function DiffBlock({
  lines,
  className,
}: {
  lines: readonly DiffLine[];
  className?: string;
}) {
  return (
    <div
      data-diff
      className={cn(
        'overflow-x-auto whitespace-pre rounded-sm bg-card-2 px-2.5 py-2 font-mono text-xs leading-[1.8]',
        className,
      )}
    >
      {lines.map((line, i) => (
        <div key={i} data-kind={line.kind} className={LINE[line.kind]}>
          <span aria-hidden className="inline-block no-underline">
            {MARK[line.kind]}
          </span>
          {SPOKEN[line.kind] && <span className="sr-only">{SPOKEN[line.kind]}</span>}
          {line.text}
        </div>
      ))}
    </div>
  );
}
