// src/ui/popover.tsx
import * as React from 'react';
import * as PopoverPrimitive from '@radix-ui/react-popover';
import { cn } from './utils';

const Popover = PopoverPrimitive.Root;
const PopoverTrigger = PopoverPrimitive.Trigger;
const PopoverAnchor = PopoverPrimitive.Anchor;

/** Glass popover that grows out of its trigger (origin = trigger) and
 * materializes (blur + scale + fade). DESIGN.md › glass-popover. */
const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align = 'start', sideOffset = 8, ...props }, ref) => (
  <PopoverPrimitive.Portal>
    <PopoverPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={cn(
        'glass z-50 w-72 origin-[--radix-popover-content-transform-origin] rounded-feature p-3 text-label text-body outline-none',
        'data-[state=open]:animate-materialize-in data-[state=closed]:animate-materialize-out',
        className,
      )}
      {...props}
    />
  </PopoverPrimitive.Portal>
));
PopoverContent.displayName = 'PopoverContent';

export { Popover, PopoverTrigger, PopoverAnchor, PopoverContent };
