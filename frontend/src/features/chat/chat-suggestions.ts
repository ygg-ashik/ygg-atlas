// Curated starter questions for the analytics assistant, grouped by
// capability. Static (no backend call) — cheap to curate, rotated client-side.

export interface SuggestionGroup {
  category: string;
  questions: string[];
}

export const SUGGESTION_GROUPS: SuggestionGroup[] = [
  {
    category: 'Revenue',
    questions: [
      'What was revenue last week?',
      'How is revenue trending this quarter?',
      'Which region drove the most revenue this month?',
      'Revenue split by brand for the last 30 days',
    ],
  },
  {
    category: 'Orders & customers',
    questions: [
      "Compare this month's orders to last month",
      'How many new customers did we acquire this week?',
      'What is the average order value this month?',
      'Top 10 gift card brands by orders this month',
    ],
  },
  {
    category: 'Funnels & conversion',
    questions: [
      'Where do users drop off in checkout?',
      'What is our checkout conversion rate this week?',
      'How did conversion change after the last campaign?',
    ],
  },
  {
    category: 'Campaigns & ads',
    questions: [
      'Which campaign had the best ROAS last month?',
      'How much did we spend on ads this week vs last week?',
      'Which channel brings the highest-value customers?',
    ],
  },
];

const pool = (): string[] => SUGGESTION_GROUPS.flatMap((g) => g.questions);

/** Fisher–Yates on a copy — take the first `n`. */
export function rotatingSuggestions(n: number): string[] {
  const items = pool();
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items.slice(0, n);
}
