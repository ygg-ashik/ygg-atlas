// src/features/command/command-trigger.tsx
import { Search } from 'lucide-react';
import { OPEN_PALETTE_EVENT } from './use-palette-open';

/** Sidebar affordance that opens the palette (same path as the ⌘K hotkey). */
export function CommandTrigger() {
  return (
    <button
      type="button"
      aria-keyshortcuts="Meta+K Control+K"
      onClick={() => window.dispatchEvent(new Event(OPEN_PALETTE_EVENT))}
      className="mt-2 flex w-full items-center gap-2 rounded-md border border-border/70 bg-card/60 px-2.5 py-1.5 text-label text-muted-foreground transition-[color,transform] duration-200 hover:text-ink active:scale-[.97]"
    >
      <Search aria-hidden className="h-3.5 w-3.5" />
      Search
      <kbd className="ml-auto font-mono text-[10.5px] text-muted-2">⌘K</kbd>
    </button>
  );
}
