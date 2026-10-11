// src/ui/textarea.tsx
import * as React from 'react';
import { FIELD_CLASS } from './field-styles';
import { cn } from './utils';

/** Multi-line field (DESIGN.md › Form fields): min 84px, vertical resize only. */
const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<'textarea'>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(FIELD_CLASS, 'min-h-[84px] resize-y leading-normal', className)}
      {...props}
    />
  ),
);
Textarea.displayName = 'Textarea';

export { Textarea };
