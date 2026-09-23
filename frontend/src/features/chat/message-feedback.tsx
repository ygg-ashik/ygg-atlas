import { useState } from 'react';
import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { setMessageFeedback, type FeedbackCategory } from '@/api/chat';

const CATEGORIES: { key: FeedbackCategory; label: string }[] = [
  { key: 'inaccurate', label: 'Inaccurate' },
  { key: 'incomplete', label: 'Incomplete' },
  { key: 'not_relevant', label: 'Not relevant' },
];

interface MessageFeedbackProps {
  messageId: string;
  initialRating: 'up' | 'down' | null;
}

/** Tiered feedback: 1-click thumbs; thumbs-down expands inline category
 * chips. Never a modal; ≤2 clicks to any rating. */
export function MessageFeedback({ messageId, initialRating }: MessageFeedbackProps) {
  const [rating, setRating] = useState<'up' | 'down' | null>(initialRating);
  const [category, setCategory] = useState<FeedbackCategory | null>(null);

  const rate = (r: 'up' | 'down') => {
    if (rating === r) return; // contract has no "unrate" — repeat click is a no-op
    setRating(r);
    setCategory(null);
    void setMessageFeedback(messageId, { rating: r });
  };

  const pickCategory = (key: FeedbackCategory) => {
    setCategory(key);
    void setMessageFeedback(messageId, { rating: 'down', category: key });
  };

  return (
    <div className="mt-1">
      <div className="flex gap-1">
        <button
          type="button"
          aria-label="Good answer"
          aria-pressed={rating === 'up'}
          data-active={rating === 'up'}
          onClick={() => rate('up')}
          className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground data-[active=true]:text-primary"
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Bad answer"
          aria-pressed={rating === 'down'}
          data-active={rating === 'down'}
          onClick={() => rate('down')}
          className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground data-[active=true]:text-destructive"
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </button>
      </div>
      {rating === 'down' && (
        <div className="mt-1 flex flex-wrap items-center gap-1">
          {CATEGORIES.map((c) => (
            <button
              key={c.key}
              type="button"
              aria-pressed={category === c.key}
              onClick={() => pickCategory(c.key)}
              className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
                category === c.key
                  ? 'border-primary/40 bg-accent text-accent-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground'
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
