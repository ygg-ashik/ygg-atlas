import type { LucideIcon } from 'lucide-react';
import { LogOut, Monitor, Moon, Sun } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Glass,
} from '@/ui';
import { useTheme } from '@/lib/theme-provider';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

interface ShellUser {
  name: string;
  email: string;
  avatar: string;
}

interface ShellProps {
  user: ShellUser | null;
  onSignOut: () => void;
  nav: NavItem[];
  /** Feature-provided sidebar content (e.g. chat threads), composed in App.tsx. */
  threads?: React.ReactNode;
  children: React.ReactNode;
}

/** App frame (DESIGN.md › Layout): 10px inset, floating heavy-glass sidebar,
 * rounded main pane. Features plug in via props so layout stays decoupled. */
export default function Shell({ user, onSignOut, nav, threads, children }: ShellProps) {
  return (
    <div className="flex h-screen gap-2.5 p-2.5">
      <Glass
        as="aside"
        variant="heavy"
        specular
        className="flex w-[236px] shrink-0 flex-col rounded-shell px-2.5 py-3.5 max-[999px]:hidden"
      >
        <div className="flex items-center gap-2.5 px-2.5 pb-3.5 pt-1">
          <span aria-hidden className="h-2.5 w-2.5 rotate-45 rounded-[3px] bg-primary" />
          <span className="font-serif text-[21px] leading-none text-ink">Atlas</span>
        </div>
        <nav className="space-y-0.5" aria-label="Primary">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
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
      </Glass>
      <main className="relative min-w-0 flex-1 overflow-hidden rounded-shell">{children}</main>
    </div>
  );
}

function ThemeToggle() {
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

function UserMenu({ user, onSignOut }: { user: ShellUser | null; onSignOut: () => void }) {
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
