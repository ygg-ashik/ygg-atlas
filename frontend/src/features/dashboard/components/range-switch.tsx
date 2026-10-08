import { motion } from 'motion/react';
import type { OverviewDays } from '@/api/overview';
import { cn, springDefault } from '@/ui';

const OPTIONS: readonly OverviewDays[] = [7, 30, 90];

interface RangeSwitchProps {
  value: OverviewDays;
  onChange: (days: OverviewDays) => void;
}

/** Apple segmented control: the thumb slides between options (shared layoutId). */
export function RangeSwitch({ value, onChange }: RangeSwitchProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Date range"
      className="relative flex rounded-full bg-foreground/[0.05] p-[3px]"
    >
      {OPTIONS.map((days) => {
        const active = days === value;
        return (
          <button
            key={days}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(days)}
            className={cn(
              'relative z-[1] rounded-full px-3 py-1.5 text-label transition-[color,transform] duration-200 active:scale-[.97]',
              active ? 'text-ink' : 'text-muted-foreground',
            )}
          >
            {active && (
              <motion.span
                layoutId="range-thumb"
                transition={springDefault}
                className="absolute inset-0 -z-[1] rounded-full bg-card shadow-[0_1px_3px_rgba(0,0,0,0.12),0_0_0_0.5px_hsl(var(--border))]"
              />
            )}
            {days}D
          </button>
        );
      })}
    </div>
  );
}
