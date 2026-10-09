// src/ui/avatar.tsx
import { Bot } from 'lucide-react';
import { cn } from './utils';

export interface AvatarProps {
  name: string;
  kind?: 'human' | 'service';
  size?: 'md' | 'lg';
  /** Give a label only when no name is shown beside the avatar. */
  label?: string;
  className?: string;
}

/** Up to two initials from a display name ("Sara Mansour" → "SM"). */
export function initials(name: string): string {
  return name
    .split(/[\s-]+/)
    .filter(Boolean)
    .map((s) => s[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
}

/** Initials disc (DESIGN.md › avatar); service identities get a rounded square
 * with a glyph (› avatar-service). Decorative unless `label` is given. */
export function Avatar({ name, kind = 'human', size = 'md', label, className }: AvatarProps) {
  const service = kind === 'service';
  return (
    <span
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      data-kind={kind}
      className={cn(
        'grid shrink-0 place-items-center font-semibold tracking-[0.02em]',
        size === 'lg' ? 'h-12 w-12 text-base' : 'h-[30px] w-[30px] text-[11px]',
        service
          ? 'rounded-[10px] bg-card-2 text-muted-foreground'
          : 'rounded-full bg-primary/10 text-primary-text',
        className,
      )}
    >
      {service ? <Bot className="h-3.5 w-3.5" /> : initials(name)}
    </span>
  );
}
