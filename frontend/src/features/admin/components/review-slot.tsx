import { FieldError, ReviewCard } from '@/ui';
import { type ReviewedWrite } from '../hooks/use-reviewed-write';

interface ReviewSlotProps {
  write: ReviewedWrite;
  slot: string;
  /** Extra cleanup when the reviewer dismisses (e.g. reset a select). */
  onDismiss?: () => void;
}

/** Renders the open review card when it belongs to `slot`. */
export function ReviewSlot({ write, slot, onDismiss }: ReviewSlotProps) {
  const { review } = write;
  if (!review || review.spec.slot !== slot) return null;
  const { spec, status, error } = review;
  return (
    <ReviewCard
      title={spec.title}
      lines={spec.lines}
      status={status}
      auditAction={spec.auditAction}
      applyLabel={spec.applyLabel}
      appliedLabel={spec.appliedLabel}
      onApply={() => void write.apply()}
      onDismiss={() => {
        write.dismiss();
        onDismiss?.();
      }}
    >
      {error && (
        <div role="alert" className="mb-2">
          <FieldError>{error}</FieldError>
        </div>
      )}
    </ReviewCard>
  );
}
