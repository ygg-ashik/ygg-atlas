// src/ui/brand-mark.tsx
import { cn } from './utils';

export interface BrandMarkProps {
  /** sidebar: 21px wordmark · display: the sign-in panel. */
  size?: 'sidebar' | 'display';
  className?: string;
}

const sizes = {
  sidebar: { gap: 'gap-2.5', diamond: 'h-2.5 w-2.5 rounded-[3px]', word: 'text-[21px]' },
  display: { gap: 'gap-3.5', diamond: 'h-3.5 w-3.5 rounded-[4px]', word: 'text-display' },
} as const;

/** The Atlas mark (DESIGN.md › brand-mark): a clay diamond beside the serif wordmark. */
export function BrandMark({ size = 'sidebar', className }: BrandMarkProps) {
  const s = sizes[size];
  return (
    <div className={cn('flex items-center', s.gap, className)}>
      <span
        aria-hidden="true"
        data-brand-diamond
        className={cn('rotate-45 bg-primary', s.diamond)}
      />
      <span className={cn('font-serif leading-none text-ink', s.word)}>Atlas</span>
    </div>
  );
}
