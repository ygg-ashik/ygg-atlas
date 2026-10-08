import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

// tailwind-merge must know the custom DESIGN.md scales from tailwind.config.js, or it
// reads `text-label` as a text color and silently drops `text-primary-foreground`.
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ['display', 'title', 'section', 'answer', 'label', 'caption', 'metric-xl', 'metric-lg'],
      radius: ['card', 'shell', 'feature', 'glass'],
    },
  },
});

/** Merge Tailwind classes; later classes win on conflicts. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
