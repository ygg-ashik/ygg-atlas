// src/features/layout/account-sheet.tsx
import { type ReactElement } from 'react';
import { ChevronRight, LogOut, Settings, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  Avatar,
  CountBadge,
  Dialog,
  DialogBareContent,
  DialogBareOverlay,
  DialogClose,
  DialogDescription,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
  RolePill,
  ThemeSwitch,
} from '@/ui';
import { useTheme } from '@/lib/theme-provider';
import { ROUTES } from '@/lib/routes';
import { SETTINGS_LIST_STATE } from './settings-list-state';
import { type AdminEntry, type ShellUser } from './types';

interface AccountSheetProps {
  trigger: ReactElement;
  user: ShellUser;
  onSignOut: () => void;
  admin?: AdminEntry;
}

const ROW =
  'flex min-h-12 w-full items-center gap-3 rounded-md px-3 text-[15px] text-ink transition-[background-color,transform] duration-200 hover:bg-foreground/5 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15 active:scale-[.98]';

/** The account menu as a glass bottom sheet below 600px (DESIGN.md ›
 * account-sheet): same items, 48px rows, the theme as a full segmented control.
 * Settings opens the drill-down list. */
export function AccountSheet({ trigger, user, onSignOut, admin }: AccountSheetProps) {
  const { theme, setTheme } = useTheme();
  const pending = admin?.pendingApprovals ?? 0;
  return (
    <Dialog>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogPortal>
        <DialogBareOverlay className="fixed inset-0 z-50 bg-[var(--scrim)] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogBareContent className="glass fixed inset-x-2 bottom-2 z-50 rounded-glass px-2 pb-3 pt-1.5 outline-none duration-500 ease-sheet data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom">
          <div aria-hidden className="mx-auto mb-1.5 mt-1 h-1 w-9 rounded-full bg-foreground/20" />
          <DialogTitle className="sr-only">Account</DialogTitle>
          <DialogDescription className="sr-only">
            Settings, admin, theme and sign out.
          </DialogDescription>
          <div className="flex items-center gap-2.5 px-3 pb-3 pt-2">
            <Avatar name={user.name || user.email} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-ink">{user.name}</div>
              <div className="truncate text-xs text-muted-foreground">{user.email}</div>
            </div>
            {user.role && <RolePill role={user.role} />}
          </div>
          <div className="mx-1.5 h-px bg-border/70" />
          <DialogClose asChild>
            <Link to={ROUTES.settings} state={SETTINGS_LIST_STATE} className={ROW}>
              <Settings aria-hidden className="h-4 w-4 text-muted-foreground" />
              Settings
              <ChevronRight aria-hidden className="ml-auto h-4 w-4 text-muted-2" />
            </Link>
          </DialogClose>
          {admin && (
            <DialogClose asChild>
              <Link to={admin.to} className={ROW}>
                <ShieldCheck aria-hidden className="h-4 w-4 text-muted-foreground" />
                Admin
                <CountBadge
                  count={pending}
                  label={pending === 1 ? 'pending approval' : 'pending approvals'}
                />
              </Link>
            </DialogClose>
          )}
          <div className="mx-1.5 my-1 h-px bg-border/70" />
          <div className="flex min-h-12 items-center gap-3 px-3">
            <span className="text-[15px] text-ink">Theme</span>
            <ThemeSwitch value={theme} onChange={setTheme} className="ml-auto" />
          </div>
          <div className="mx-1.5 my-1 h-px bg-border/70" />
          <DialogClose asChild>
            <button type="button" className={ROW} onClick={onSignOut}>
              <LogOut aria-hidden className="h-4 w-4 text-muted-foreground" />
              Sign out
            </button>
          </DialogClose>
        </DialogBareContent>
      </DialogPortal>
    </Dialog>
  );
}
