import { FieldError, ReviewCard, type DiffLine, type ReviewStatus } from '@/ui';

/** The state of the revoke mutation the card drives. */
export interface RevokeMutationState {
  isPending: boolean;
  isSuccess: boolean;
  errorInfo: { message: string } | null;
}

interface RevokeReviewProps {
  title: string;
  lines: readonly DiffLine[];
  /** The credential event the revoke records, e.g. `token.revoke`. */
  auditAction: string;
  applyLabel: string;
  mutation: RevokeMutationState;
  onApply: () => void;
  onDismiss: () => void;
}

function statusOf({ isPending, isSuccess }: RevokeMutationState): ReviewStatus {
  if (isSuccess) return 'applied';
  return isPending ? 'applying' : 'open';
}

/** A self-service revoke, reviewed before it runs (destructive writes always are). */
export function RevokeReview({ mutation, ...card }: RevokeReviewProps) {
  return (
    <ReviewCard {...card} appliedLabel="Revoked" status={statusOf(mutation)}>
      {mutation.errorInfo && (
        <div role="alert" className="mb-2">
          <FieldError>{mutation.errorInfo.message}</FieldError>
        </div>
      )}
    </ReviewCard>
  );
}
