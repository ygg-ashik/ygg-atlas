// Curated starter questions for the analytics assistant, grouped by
// capability. Static (no backend call) — cheap to curate, rotated client-side.

export interface SuggestionGroup {
  category: string;
  questions: string[];
}

export const SUGGESTION_GROUPS: SuggestionGroup[] = [
  {
    category: 'Revenue & orders',
    questions: [
      'What was revenue last week?',
      "Compare this month's orders to last month",
      'What is the average order value this month?',
      'What was total corporate revenue in AED this year?',
    ],
  },
  {
    category: 'Portfolio health',
    questions: [
      'How many accounts are currently at risk?',
      'What does the health band distribution look like?',
      'Which are our top 10 accounts by YTD revenue?',
    ],
  },
  {
    category: 'Tasks & CSMs',
    questions: [
      'How many tasks are overdue right now?',
      'How are open tasks distributed across CSMs?',
      'How many tasks were completed this month?',
    ],
  },
  {
    category: 'Funnels & leads',
    questions: [
      'Where do users drop off in checkout?',
      'Show the lead pipeline funnel for this year',
      'How many leads came in this month, by channel?',
    ],
  },
];

const pool = (): string[] => SUGGESTION_GROUPS.flatMap((g) => g.questions);

/** Fisher–Yates on a copy — take the first `n`. */
export function rotatingSuggestions(n: number): string[] {
  const items = pool();
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const current = items[i];
    const other = items[j];
    if (current === undefined || other === undefined) continue;
    items[i] = other;
    items[j] = current;
  }
  return items.slice(0, n);
}
