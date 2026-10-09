// Review before apply: every widening or destructive write is staged as a
// review card first and runs only on Apply. A stale-actor 409 turns the card
// into its conflict state and raises an action toast with Retry; any other
// failure keeps the card open with the backend's sentence.
import { useCallback, useRef, useState } from 'react';
import { describeMutationError } from '@/api/mutation-errors';
import { actionToast, type DiffLine, type ReviewStatus } from '@/ui';

export interface ReviewSpec {
  /** Which slot on the page renders this card. */
  slot: string;
  title: string;
  /** The audit action the write records, e.g. `grant.create`. */
  auditAction: string;
  lines: readonly DiffLine[];
  applyLabel?: string;
  appliedLabel?: string;
  /** Offer Retry on a 409 (true for AccessAdmin writes, whose 409 is the stale actor). */
  retryOn409?: boolean;
  /** The write itself (a mutation's `mutateAsync`). */
  run: () => Promise<unknown>;
}

export interface ReviewState {
  spec: ReviewSpec;
  status: ReviewStatus;
  error: string | null;
}

export interface ReviewedWrite {
  review: ReviewState | null;
  open: (spec: ReviewSpec) => void;
  dismiss: () => void;
  apply: () => Promise<void>;
}

export function useReviewedWrite(): ReviewedWrite {
  const [review, setReview] = useState<ReviewState | null>(null);
  const current = useRef<ReviewState | null>(null);
  current.current = review;

  const open = useCallback((spec: ReviewSpec) => {
    setReview({ spec, status: 'open', error: null });
  }, []);
  const dismiss = useCallback(() => setReview(null), []);

  const apply = useCallback(async () => {
    const state = current.current;
    if (!state || state.status === 'applying' || state.status === 'applied') return;
    const { spec } = state;
    const still = (s: ReviewState | null) => s?.spec === spec;
    setReview((s) => (still(s) ? { spec, status: 'applying', error: null } : s));
    try {
      await spec.run();
      setReview((s) => (still(s) ? { spec, status: 'applied', error: null } : s));
    } catch (error) {
      const info = describeMutationError(error, { retryOn409: spec.retryOn409 ?? true });
      if (info.retry) {
        setReview((s) => (still(s) ? { spec, status: 'conflict', error: null } : s));
        actionToast(info.message, {
          actionLabel: info.retry.actionLabel,
          onAction: () => void apply(),
        });
        return;
      }
      setReview((s) => (still(s) ? { spec, status: 'open', error: info.message } : s));
    }
  }, []);

  return { review, open, dismiss, apply };
}
