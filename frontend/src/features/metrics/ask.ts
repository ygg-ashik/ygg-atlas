// src/features/metrics/ask.ts
// Entry point into chat: /ask?q=… (handled by the chat feature).

/** A catalog entry: metrics carry a time scope, funnels don't. */
export interface AskTarget {
  name: string;
  time_scope?: 'range' | 'snapshot';
}

/** Link that opens chat with a governed-metric question prefilled. */
export function askHref(item: AskTarget): string {
  return `/ask?q=${encodeURIComponent(question(item))}`;
}

function question(item: AskTarget): string {
  if (item.time_scope === 'snapshot') return `What is ${item.name} right now?`;
  if (item.time_scope === 'range') return `What was ${item.name} over the last 30 days?`;
  return `Where do users drop off in ${item.name} over the last 30 days?`;
}
