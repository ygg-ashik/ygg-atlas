// src/features/command/use-palette-open.ts
import { useEffect, useState } from 'react';

/** Fired by `CommandTrigger` so the button and the hotkey share one code path. */
export const OPEN_PALETTE_EVENT = 'atlas:open-command-palette';

function isPaletteHotkey(e: KeyboardEvent): boolean {
  return (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k';
}

/** Palette open state: ⌘K / Ctrl+K toggles it, the trigger event opens it. */
export function usePaletteOpen() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!isPaletteHotkey(e)) return;
      e.preventDefault();
      setOpen((o) => !o);
    };
    const onOpen = () => setOpen(true);
    window.addEventListener('keydown', onKey);
    window.addEventListener(OPEN_PALETTE_EVENT, onOpen);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener(OPEN_PALETTE_EVENT, onOpen);
    };
  }, []);

  return [open, setOpen] as const;
}
