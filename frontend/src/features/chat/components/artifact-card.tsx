import { ArrowRight, Table2 } from 'lucide-react';
import type { ArtifactBlock } from '@/api/chat';

interface ArtifactCardProps {
  artifact: ArtifactBlock;
  onOpen: () => void;
}

/** Inline card linking to the artifact side panel (DESIGN.md › artifact-card). */
export function ArtifactCard({ artifact, onOpen }: ArtifactCardProps) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="my-2.5 flex w-full items-center gap-3 rounded-card bg-card px-3.5 py-3 text-left shadow-[0_0_0_1px_hsl(var(--border)/0.6)] transition-[box-shadow,transform] duration-300 ease-out hover:shadow-[0_0_0_1px_hsl(var(--border)),0_8px_24px_rgba(0,0,0,0.08)] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15 active:scale-[.99]"
    >
      <span
        aria-hidden
        className="grid h-10 w-10 shrink-0 place-items-center rounded-[11px] bg-primary/10 text-primary-text"
      >
        <Table2 className="h-[18px] w-[18px]" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-label font-semibold text-ink">{artifact.title}</span>
        <span className="block text-caption text-muted-foreground">
          Chart + table · opens in side panel
        </span>
      </span>
      <ArrowRight aria-hidden className="h-4 w-4 text-muted-2" />
    </button>
  );
}
