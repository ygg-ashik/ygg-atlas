// src/ui/skeleton.tsx
import type * as React from 'react';
import { cn } from './utils';

const SHAPE = {
  line: 'h-3 rounded-sm',
  heading: 'h-[30px] w-2/5 rounded-[10px]',
  circle: 'h-[30px] w-[30px] shrink-0 rounded-full',
} as const;

export interface SkeletonProps {
  shape?: keyof typeof SHAPE;
  className?: string;
  style?: React.CSSProperties;
}

/** A recessed placeholder bar in the shape of what is coming (DESIGN.md › skeleton).
 * The shimmer is a passive CSS loop; reduced motion stops it via index.css. */
export function Skeleton({ shape = 'line', className, style }: SkeletonProps) {
  return (
    <span
      aria-hidden
      data-skeleton={shape}
      style={style}
      className={cn(
        'block animate-shimmer bg-[linear-gradient(90deg,hsl(var(--ink)/0.07)_0%,hsl(var(--ink)/0.03)_50%,hsl(var(--ink)/0.07)_100%)] bg-[length:200%_100%]',
        SHAPE[shape],
        className,
      )}
    />
  );
}

/** Busy region wrapping skeletons; announces what is loading. */
export function SkeletonRegion({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div aria-busy="true" className={className}>
      <span role="status" className="sr-only">
        Loading {label}
      </span>
      {children}
    </div>
  );
}

/** List-row skeletons: avatar, two lines, a trailing pill. */
export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="flex min-h-[52px] items-center gap-3.5 border-b border-border/50 px-4 py-3 last:border-b-0"
        >
          <Skeleton shape="circle" />
          <div className="grid flex-1 gap-[7px]">
            <Skeleton style={{ width: `${30 + ((i * 17) % 35)}%` }} />
            <Skeleton className="h-[9px]" style={{ width: `${18 + ((i * 11) % 25)}%` }} />
          </div>
          <Skeleton className="h-[18px] w-16" />
        </div>
      ))}
    </>
  );
}
