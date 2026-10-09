// src/ui/toaster.tsx
import { Toaster as Sonner, toast } from 'sonner';

/** Glass toasts, bottom-right, stacking. Only for completions that happen away
 * from their trigger (DESIGN.md › toast); in-place feedback morphs instead.
 * `actionToast` adds the warning tone with one action (› action-toast). */
export function Toaster() {
  return (
    <Sonner
      position="bottom-right"
      gap={10}
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            'glass flex w-[300px] items-center gap-2.5 rounded-lg px-3.5 py-3 text-label text-ink',
          title: 'font-medium',
          description: 'text-caption text-muted-foreground',
          icon: 'text-positive',
          actionButton:
            'ml-auto shrink-0 rounded-full border border-border bg-card px-2.5 py-1 text-xs font-medium text-body transition-transform active:scale-[.96] hover:border-primary hover:text-ink',
          closeButton:
            'absolute -left-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full border border-border bg-card text-muted-foreground [&_svg]:h-3 [&_svg]:w-3',
        },
      }}
    />
  );
}

export { toast };
