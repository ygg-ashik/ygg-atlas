// src/ui/toaster.tsx
import { Toaster as Sonner, toast } from 'sonner';

/** Glass toasts, bottom-right, stacking. Only for completions that happen away
 * from their trigger (DESIGN.md › toast); in-place feedback morphs instead. */
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
        },
      }}
    />
  );
}

export { toast };
