// src/ui/roving.ts
// Shared keyboard model for composite widgets (segmented control, radio list):
// arrows move to the next enabled item and wrap, Home/End jump to the ends.

const NEXT = new Set(['ArrowRight', 'ArrowDown']);
const PREV = new Set(['ArrowLeft', 'ArrowUp']);

function step(from: number, delta: 1 | -1, enabled: readonly boolean[]): number {
  const n = enabled.length;
  for (let i = 1; i <= n; i += 1) {
    const at = (((from + delta * i) % n) + n) % n;
    if (enabled[at]) return at;
  }
  return from;
}

/** Index the key moves focus to, or null when the key is not a navigation key. */
export function moveIndex(key: string, from: number, enabled: readonly boolean[]): number | null {
  if (enabled.length === 0) return null;
  if (NEXT.has(key)) return step(from, 1, enabled);
  if (PREV.has(key)) return step(from, -1, enabled);
  if (key === 'Home') return step(-1, 1, enabled);
  if (key === 'End') return step(enabled.length, -1, enabled);
  return null;
}
