import { LogOut, Monitor, Moon, Orbit, Sun } from 'lucide-react';
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Separator,
} from '@/ui';
import { useTheme } from '@/lib/theme-provider';

interface ShellUser {
  name: string;
  email: string;
  avatar: string;
}

interface ShellProps {
  user: ShellUser | null;
  onSignOut: () => void;
  children: React.ReactNode;
}

/** App frame: brand header with theme toggle + user menu, content below.
 * Receives the user via props so layout stays decoupled from the auth feature. */
export default function Shell({ user, onSignOut, children }: ShellProps) {
  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="flex h-14 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Orbit className="h-5 w-5" />
          </div>
          <div className="leading-tight">
            <span className="block text-sm font-semibold tracking-tight">Atlas</span>
            <span className="block text-[10px] text-muted-foreground">
              YouGotAGift data intelligence
            </span>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <ThemeToggle />
          <Separator orientation="vertical" className="mx-1 h-6" />
          <UserMenu user={user} onSignOut={onSignOut} />
        </div>
      </header>

      <main className="min-h-0 flex-1">{children}</main>
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
    <DropdownMenuItem
      onSelect={onSelect}
      className={active ? 'bg-accent text-accent-foreground' : ''}
    >
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
          className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border bg-muted text-xs font-medium transition-opacity hover:opacity-80"
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
