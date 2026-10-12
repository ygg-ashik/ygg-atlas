// src/features/layout/use-settings-hotkeys.ts
import { useEffect, useRef } from 'react';

interface SettingsHotkeys {
  inSettings: boolean;
  /** ⌘, / Ctrl+, from anywhere in the app. */
  onOpen: () => void;
  /** Escape inside Settings. */
  onBack: () => void;
}

/** Escape belongs to whatever is on top: an open dialog, menu or listbox, or a
 * field the user is typing in. Only a bare page hands it to Settings. */
function escapeIsTaken(e: KeyboardEvent): boolean {
  if (e.defaultPrevented) return true;
  const target = e.target;
  if (
    target instanceof HTMLElement &&
    target.closest('input, textarea, select, [contenteditable]')
  ) {
    return true;
  }
  const open = '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]';
  return document.querySelector(open) !== null;
}

/** ⌘, opens Settings; Escape leaves it (DESIGN.md › settings-rail). */
export function useSettingsHotkeys({ inSettings, onOpen, onBack }: SettingsHotkeys) {
  const latest = useRef({ inSettings, onOpen, onBack });
  latest.current = { inSettings, onOpen, onBack };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const now = latest.current;
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        now.onOpen();
        return;
      }
      if (e.key === 'Escape' && now.inSettings && !escapeIsTaken(e)) now.onBack();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
