// src/ui/action-toast.tsx
import { toast } from 'sonner';

export interface ActionToastOptions {
  /** Defaults to "Retry". */
  actionLabel?: string;
  onAction: () => void;
}

/** Warning-tone glass toast with one action (DESIGN.md › action-toast), e.g. the
 * stale-actor 409. It stays until acted on or dismissed. Needs <Toaster />. */
export function actionToast(
  message: string,
  { actionLabel = 'Retry', onAction }: ActionToastOptions,
) {
  return toast.warning(message, {
    duration: Infinity,
    closeButton: true,
    icon: (
      <span
        aria-hidden
        className="grid h-[22px] w-[22px] place-items-center rounded-full bg-warning/20 text-xs font-bold text-warning"
      >
        !
      </span>
    ),
    action: { label: actionLabel, onClick: onAction },
  });
}
