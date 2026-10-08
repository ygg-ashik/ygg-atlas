// src/features/layout/account-controls.tsx
import { LogOut, Monitor, Moon, Sun } from 'lucide-react';
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/ui';
import { useTheme } from '@/lib/theme-provider';

export interface ShellUser {
  name: string;
  email: string;
  avatar: string;
}

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Toggle theme">
          <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
          <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuCheckItem active={theme === 'light'} onSelect={() => setTheme('light')}>
          <Sun className="h-4 w-4" /> Light
        </DropdownMenuCheckItem>
        <DropdownMenuCheckItem active={theme === 'dark'} onSelect={() => setTheme('dark')}>
          <Moon className="h-4 w-4" /> Dark
        </DropdownMenuCheckItem>
        <DropdownMenuCheckItem active={theme === 'system'} onSelect={() => setTheme('system')}>
          <Monitor className="h-4 w-4" /> System
        </DropdownMenuCheckItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function DropdownMenuCheckItem({
  active,
  onSelect,
  children,
}: {
  active: boolean;
  onSelect: () => void;
  children: React.ReactNode;
}) {
  return (
    <DropdownMenuItem onSelect={onSelect} className={active ? 'bg-primary/10 text-ink' : ''}>
      {children}
    </DropdownMenuItem>
  );
}

export function UserMenu({ user, onSignOut }: { user: ShellUser | null; onSignOut: () => void }) {
  if (!user) return null;
  const initial = (user.name || user.email || '?').charAt(0).toUpperCase();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border bg-card-2 text-caption font-medium transition-transform active:scale-95"
        >
          {user.avatar ? (
            <img
              src={user.avatar}
              alt={user.name}
              referrerPolicy="no-referrer"
              className="h-full w-full object-cover"
            />
          ) : (
            initial
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="font-normal">
          <span className="block truncate text-sm font-medium text-foreground">{user.name}</span>
          <span className="block truncate text-xs text-muted-foreground">{user.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onSignOut}>
          <LogOut className="h-4 w-4" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
