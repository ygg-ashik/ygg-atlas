import { useEffect, useRef, useState } from 'react';
import { Check, Copy, ThumbsDown, ThumbsUp } from 'lucide-react';
import { setMessageFeedback, type FeedbackCategory } from '@/api/chat';
import { Button, cn } from '@/ui';

const CATEGORIES: { key: FeedbackCategory; label: string }[] = [
  { key: 'inaccurate', label: 'Inaccurate' },
  { key: 'incomplete', label: 'Incomplete' },
  { key: 'not_relevant', label: 'Not relevant' },
];

type Rating = 'up' | 'down';

interface MessageActionsProps {
  messageId: string;
  text: string;
  initialRating: Rating | null;
}

const ICON_BTN =
  'grid h-8 w-8 place-items-center rounded-full text-muted-foreground transition-[color,background-color,transform] duration-200 hover:bg-foreground/5 hover:text-ink focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15 active:scale-90';
const MORPH = 'h-3.5 w-3.5 transition-all duration-300 ease-out';
const HIDDEN = 'scale-50 opacity-0 blur-[3px]';
const COPIED_MS = 1500;

/** Copy → check morph in place; reverts after a moment. */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      return; // clipboard denied: nothing changed, so nothing to confirm
    }
    setCopied(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), COPIED_MS);
  };

  return (
    <button
      type="button"
      aria-label={copied ? 'Copied' : 'Copy answer'}
      onClick={() => void copy()}
      className={ICON_BTN}
    >
      <span className="relative grid place-items-center">
        <Copy aria-hidden className={cn(MORPH, copied && HIDDEN)} />
        <Check aria-hidden className={cn(MORPH, 'absolute text-positive', !copied && HIDDEN)} />
      </span>
    </button>
  );
}

function Categories({
  selected,
  onPick,
}: {
  selected: FeedbackCategory | null;
  onPick: (c: FeedbackCategory) => void;
}) {
  return (
    <div className="mt-1 flex flex-wrap gap-1.5">
      {CATEGORIES.map((c) => (
        <Button
          key={c.key}
          variant="pill"
          size="sm"
          data-selected={selected === c.key}
          aria-pressed={selected === c.key}
          onClick={() => onPick(c.key)}
          className="h-7 text-caption"
        >
          {c.label}
        </Button>
      ))}
    </div>
  );
}

/** In-place feedback (DESIGN.md › Feedback vocabulary): icons morph where you
 * clicked; no toast for things the user can already see change. */
export function MessageActions({ messageId, text, initialRating }: MessageActionsProps) {
  const [rating, setRating] = useState(initialRating);
  const [category, setCategory] = useState<FeedbackCategory | null>(null);

  const rate = (r: Rating) => {
    if (rating === r) return; // the contract has no "unrate": a repeat click is a no-op
    setRating(r);
    setCategory(null);
    void setMessageFeedback(messageId, { rating: r });
  };
  const pick = (c: FeedbackCategory) => {
    setCategory(c);
    void setMessageFeedback(messageId, { rating: 'down', category: c });
  };

  return (
    <div className="mt-1">
      <div className="flex gap-0.5">
        <CopyButton text={text} />
        <button
          type="button"
          aria-label="Good answer"
          aria-pressed={rating === 'up'}
          onClick={() => rate('up')}
          className={cn(ICON_BTN, rating === 'up' && 'text-primary-text')}
        >
          <ThumbsUp aria-hidden className={cn('h-3.5 w-3.5', rating === 'up' && 'fill-current')} />
        </button>
        <button
          type="button"
          aria-label="Bad answer"
          aria-pressed={rating === 'down'}
          onClick={() => rate('down')}
          className={cn(ICON_BTN, rating === 'down' && 'text-negative')}
        >
          <ThumbsDown
            aria-hidden
            className={cn('h-3.5 w-3.5', rating === 'down' && 'fill-current')}
          />
        </button>
      </div>
      {rating === 'down' && <Categories selected={category} onPick={pick} />}
    </div>
  );
}
