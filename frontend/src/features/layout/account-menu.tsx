// src/features/layout/account-menu.tsx
import { LogOut, Settings, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  Avatar,
  CountBadge,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  RolePill,
  THEME_CHOICES,
  UserChip,
} from '@/ui';
import { useTheme } from '@/lib/theme-provider';
import { ROUTES } from '@/lib/routes';
import { useMediaQuery } from '@/lib/use-media-query';
import { AccountSheet } from './account-sheet';
import { type AdminEntry, type ShellUser } from './types';

/** Below 600px the menu is a bottom sheet (DESIGN.md › settings-drilldown). */
export const PHONE_QUERY = '(max-width: 599px)';

export interface AccountMenuProps {
  user: ShellUser | null;
  onSignOut: () => void;
  /** Present only for managers and admins (App.tsx decides from `/me/access`). */
  admin?: AdminEntry;
}

/** Screen-reader meaning of the pending-approvals count. */
function approvalsLabel(count: number): string {
  return count === 1 ? '1 pending approval' : `${count} pending approvals`;
}

/** The user chip at the sidebar foot and the account menu it opens (DESIGN.md ›
 * account-menu): header, Settings (⌘,), Admin for managers and admins, theme,
 * sign out. A bottom sheet below 600px. */
export function AccountMenu({ user, onSignOut, admin }: AccountMenuProps) {
  const phone = useMediaQuery(PHONE_QUERY, false);
  if (!user) return null;
  const pending = admin?.pendingApprovals ?? 0;
  const trigger = (
    <button
      type="button"
      aria-label="Account menu"
      className="block w-full rounded-[14px] text-left transition-[background-color,transform] duration-200 hover:bg-foreground/5 active:scale-[.98] data-[state=open]:bg-card"
    >
      <UserChip
        name={user.name}
        email={user.email}
        role={user.role ? <RolePill role={user.role} /> : undefined}
        dot={pending > 0 ? approvalsLabel(pending) : undefined}
      />
    </button>
  );
  if (phone) {
    return <AccountSheet trigger={trigger} user={user} onSignOut={onSignOut} admin={admin} />;
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={8}
        className="w-[276px] rounded-shell"
      >
        <DropdownMenuLabel className="flex items-center gap-2.5 px-2.5 pb-3 pt-2.5 font-normal">
          <Avatar name={user.name || user.email} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-ink">{user.name}</span>
            <span className="block truncate text-xs text-muted-foreground">{user.email}</span>
          </span>
          {user.role && <RolePill role={user.role} />}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to={ROUTES.settings} aria-keyshortcuts="Meta+Comma">
            <Settings aria-hidden className="h-4 w-4 text-muted-foreground" />
            Settings
            <kbd className="ml-auto font-mono text-[11px] text-muted-foreground">⌘,</kbd>
          </Link>
        </DropdownMenuItem>
        {admin && (
          <DropdownMenuItem asChild>
            <Link to={admin.to}>
              <ShieldCheck aria-hidden className="h-4 w-4 text-muted-foreground" />
              Admin
              <CountBadge
                count={pending}
                label={pending === 1 ? 'pending approval' : 'pending approvals'}
              />
            </Link>
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <ThemeRadios />
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onSignOut}>
          <LogOut aria-hidden className="h-4 w-4 text-muted-foreground" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Theme as menu radio items laid out like a compact segmented capsule; they
 * keep the menu open so the change is seen in place. */
function ThemeRadios() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="px-2.5 py-1.5">
      <div className="mb-1.5 text-caption text-muted-foreground">Theme</div>
      <DropdownMenuRadioGroup
        aria-label="Theme"
        value={theme}
        onValueChange={(v) => {
          const choice = THEME_CHOICES.find((c) => c.value === v);
          if (choice) setTheme(choice.value);
        }}
        className="flex gap-0.5 rounded-full bg-card-2 p-[3px] shadow-[inset_0_0_0_1px_hsl(var(--border)/0.5)]"
      >
        {THEME_CHOICES.map(({ value, label, icon: Icon }) => (
          <DropdownMenuRadioItem
            key={value}
            value={value}
            onSelect={(e) => e.preventDefault()}
            className="flex flex-1 items-center justify-center gap-1 rounded-full px-2 py-1 text-xs font-medium text-muted-foreground transition-[background-color,color] duration-200 data-[highlighted]:text-ink data-[state=checked]:bg-card data-[state=checked]:text-ink data-[state=checked]:shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_3px_rgba(0,0,0,0.08)] data-[highlighted]:ring-2 data-[highlighted]:ring-primary/20"
          >
            <Icon aria-hidden className="h-3 w-3" />
            {label}
          </DropdownMenuRadioItem>
        ))}
      </DropdownMenuRadioGroup>
    </div>
  );
}
