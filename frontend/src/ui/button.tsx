import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from './utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium transition-[transform,background-color,border-color,color,filter] duration-200 ease-out active:scale-[.97] active:duration-100 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default: 'rounded-full bg-primary text-primary-foreground hover:brightness-105',
        pill: 'rounded-full border border-border bg-card text-body hover:border-primary hover:text-ink data-[selected=true]:border-primary data-[selected=true]:bg-primary data-[selected=true]:text-primary-foreground',
        send: 'rounded-full bg-primary text-primary-foreground shadow-[0_4px_14px_hsl(var(--primary)/0.35)]',
        ghost: 'rounded-full text-ink hover:bg-foreground/5',
        outline: 'rounded-full border border-border bg-card text-ink hover:bg-foreground/5',
        secondary: 'rounded-full bg-secondary text-secondary-foreground hover:bg-secondary/80',
        destructive: 'rounded-full bg-destructive text-destructive-foreground hover:brightness-105',
        link: 'text-primary-text underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 text-label',
        sm: 'h-8 px-3 text-label',
        lg: 'h-10 px-6 text-sm',
        icon: 'h-9 w-9 rounded-full',
        send: 'h-9 w-9',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  },
);
Button.displayName = 'Button';

export { Button, buttonVariants };
