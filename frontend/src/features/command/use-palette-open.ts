// src/features/command/use-palette-open.ts
import { useEffect, useRef, useState } from 'react';

/** Fired by `CommandTrigger` so the button and the hotkey share one code path. */
export const OPEN_PALETTE_EVENT = 'atlas:open-command-palette';

function isPaletteHotkey(e: KeyboardEvent): boolean {
  return (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k';
}

/** Palette open state: ⌘K / Ctrl+K toggles it, the trigger event opens it.
 * `notify` hears every change (App.tsx loads quick-action data while open). */
export function usePaletteOpen(notify?: (open: boolean) => void) {
  const [open, setOpen] = useState(false);
  const notifyRef = useRef(notify);
  notifyRef.current = notify;
  useEffect(() => {
    notifyRef.current?.(open);
  }, [open]);

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
