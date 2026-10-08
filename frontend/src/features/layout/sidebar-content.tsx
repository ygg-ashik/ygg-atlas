// src/features/layout/sidebar-content.tsx
import type { LucideIcon } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { cn } from '@/ui';
import { type ShellUser, ThemeToggle, UserMenu } from './account-controls';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

export interface SidebarContentProps {
  user: ShellUser | null;
  onSignOut: () => void;
  nav: NavItem[];
  /** Feature-provided sidebar content (e.g. chat threads), composed in App.tsx. */
  threads?: React.ReactNode;
}

/** Brand, primary nav, the threads slot and the account row. Rendered by the
 * docked sidebar (≥1000px) and by the navigation drawer (<1000px). */
export function SidebarContent({ user, onSignOut, nav, threads }: SidebarContentProps) {
  return (
    <>
      <div className="flex items-center gap-2.5 px-2.5 pb-3.5 pt-1">
        <span aria-hidden className="h-2.5 w-2.5 rotate-45 rounded-[3px] bg-primary" />
        <span className="font-serif text-[21px] leading-none text-ink">Atlas</span>
      </div>
      <nav className="space-y-0.5" aria-label="Primary">
        {nav.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-[background-color,transform] duration-200 active:scale-[.97]',
                isActive
                  ? 'bg-card text-ink shadow-[0_0_0_1px_hsl(var(--border)),0_1px_3px_rgba(0,0,0,0.06)]'
                  : 'text-body hover:bg-foreground/5',
              )
            }
          >
            <Icon className="h-4 w-4 opacity-75" />
            {label}
          </NavLink>
        ))}
      </nav>
      {threads}
      <div className="mt-auto flex items-center gap-1 border-t border-border/60 px-1 pt-2.5">
        <UserMenu user={user} onSignOut={onSignOut} />
        <span className="min-w-0 flex-1 truncate text-label text-muted-foreground">
          {user?.name}
        </span>
        <ThemeToggle />
      </div>
    </>
  );
}
