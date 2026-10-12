// src/ui/theme-switch.tsx
import type { LucideIcon } from 'lucide-react';
import { Monitor, Moon, Sun } from 'lucide-react';
import { SegmentedControl } from './segmented-control';

export type ThemeChoice = 'light' | 'dark' | 'system';

/** The three appearance choices, in display order, with their glyphs. */
export const THEME_CHOICES: readonly { value: ThemeChoice; label: string; icon: LucideIcon }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
];

export interface ThemeSwitchProps {
  value: ThemeChoice;
  onChange: (value: ThemeChoice) => void;
  className?: string;
}

/** Light · Dark · System as a radio `segmented-control` (Settings › General and
 * the mobile account sheet). Applies on change; there is nothing to save. */
export function ThemeSwitch({ value, onChange, className }: ThemeSwitchProps) {
  return (
    <SegmentedControl
      kind="radio"
      label="Theme"
      value={value}
      onChange={onChange}
      className={className}
      options={THEME_CHOICES.map(({ value: v, label, icon: Icon }) => ({
        value: v,
        label: (
          <>
            <Icon aria-hidden className="h-3.5 w-3.5" />
            {label}
          </>
        ),
      }))}
    />
  );
}
