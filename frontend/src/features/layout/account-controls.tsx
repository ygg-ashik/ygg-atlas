// src/features/layout/account-controls.tsx
import type { LucideIcon } from 'lucide-react';
import { LogOut, Monitor, Moon, Sun } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  RolePill,
  UserChip,
} from '@/ui';
import { useTheme } from '@/lib/theme-provider';

export interface ShellUser {
  name: string;
  email: string;
  avatar: string;
  /** The role from the backend's `/me/access`; omitted until it answers. */
  role?: string;
}

/** A link offered in the account menu ("My access", "Tokens & apps"). */
export interface AccountMenuItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

type Theme = 'light' | 'dark' | 'system';
const THEMES: { value: Theme; label: string; icon: LucideIcon }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
];

/** The signed-in person at the sidebar foot (DESIGN.md › user-chip). The chip
 * opens the account menu: composed links, theme, sign out. */
export function UserMenu({
  user,
  onSignOut,
  items = [],
}: {
  user: ShellUser | null;
  onSignOut: () => void;
  items?: AccountMenuItem[];
}) {
  if (!user) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          className="block w-full rounded-[14px] text-left transition-[background-color,transform] duration-200 hover:bg-foreground/5 active:scale-[.98]"
        >
          <UserChip
            name={user.name}
            email={user.email}
            role={user.role ? <RolePill role={user.role} /> : undefined}
          />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-56">
        <DropdownMenuLabel className="font-normal">
          <span className="block truncate text-sm font-medium text-foreground">{user.name}</span>
          <span className="block truncate text-xs text-muted-foreground">{user.email}</span>
        </DropdownMenuLabel>
        {items.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              {items.map(({ to, label, icon: Icon }) => (
                <DropdownMenuItem key={to} asChild>
                  <Link to={to}>
                    <Icon aria-hidden className="h-4 w-4" /> {label}
                  </Link>
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </>
        )}
        <DropdownMenuSeparator />
        <ThemeItems />
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onSignOut}>
          <LogOut aria-hidden className="h-4 w-4" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ThemeItems() {
  const { theme, setTheme } = useTheme();
  return (
    <DropdownMenuGroup aria-label="Theme">
      {THEMES.map(({ value, label, icon: Icon }) => (
        <DropdownMenuItem
          key={value}
          onSelect={() => setTheme(value)}
          aria-current={theme === value ? 'true' : undefined}
          className={theme === value ? 'bg-primary/10 text-ink' : ''}
        >
          <Icon aria-hidden className="h-4 w-4" /> {label}
        </DropdownMenuItem>
      ))}
    </DropdownMenuGroup>
  );
}
