import { useEffect, useRef } from 'react';
import { type ReviewedWrite } from './use-reviewed-write';

/** A review card that is the whole dialog (⌘K quick actions): opened once on
 * mount by `start`, and the dialog closes when the reviewer dismisses it. */
export function useReviewDialog(write: ReviewedWrite, start: () => void, onClose: () => void) {
  const started = useRef(false);
  const shown = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    start();
  }, [start]);
  const open = write.review !== null;
  if (open) shown.current = true;
  useEffect(() => {
    if (shown.current && !open) onClose();
  }, [open, onClose]);
}
