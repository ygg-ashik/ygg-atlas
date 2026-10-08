// src/ui/glass.tsx
import * as React from 'react';
import { cn } from './utils';

type GlassElement = 'div' | 'aside' | 'header' | 'section' | 'form' | 'nav';

export interface GlassProps extends React.HTMLAttributes<HTMLElement> {
  as?: GlassElement;
  /** chrome: toolbars/composer/popovers · heavy: structural regions (sidebar). */
  variant?: 'chrome' | 'heavy';
  /** Liquid-Glass light response: a soft highlight follows the pointer. */
  specular?: boolean;
}

/** Floating translucent chrome (DESIGN.md › Elevation & Depth). Never put data on it. */
export const Glass = React.forwardRef<HTMLElement, GlassProps>(function Glass(
  { as = 'div', variant = 'chrome', specular = false, className, onPointerMove, ...props },
  ref,
) {
  const handlePointerMove = (e: React.PointerEvent<HTMLElement>) => {
    if (specular) {
      const rect = e.currentTarget.getBoundingClientRect();
      e.currentTarget.style.setProperty('--spec-x', `${e.clientX - rect.left}px`);
      e.currentTarget.style.setProperty('--spec-y', `${e.clientY - rect.top}px`);
    }
    onPointerMove?.(e);
  };
  return React.createElement(as, {
    ref,
    'data-glass': variant,
    className: cn(
      'glass',
      variant === 'heavy' && 'glass-heavy',
      specular && 'glass-specular',
      className,
    ),
    onPointerMove: handlePointerMove,
    ...props,
  });
});
