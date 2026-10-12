// src/features/layout/settings-list.tsx
import { ArrowLeft, ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Avatar, CountBadge, RolePill, cn } from '@/ui';
import { type NavSection, type ShellUser } from './types';

interface SettingsListProps {
  sections: readonly NavSection[];
  user: ShellUser | null;
  onBack: () => void;
  onSignOut: () => void;
}

const LIST =
  'overflow-hidden rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.5)] [&>*+*]:border-t [&>*+*]:border-border/50';
const ROW =
  'flex min-h-12 items-center gap-3 px-4 py-2.5 text-[15px] text-ink transition-colors duration-200 hover:bg-foreground/5 focus-visible:bg-foreground/5 focus-visible:outline-none';

/** Settings below 600px (DESIGN.md › settings-drilldown): the person, then You
 * and Organization as grouped rows with chevrons; a row opens its page. */
export function SettingsList({ sections, user, onBack, onSignOut }: SettingsListProps) {
  return (
    <div className="absolute inset-0 overflow-y-auto">
      <div className="mx-auto max-w-[560px] px-4 pb-16 pt-4">
        <button
          type="button"
          onClick={onBack}
          className="flex h-11 items-center gap-1.5 rounded-full px-2 text-[15px] text-primary-text active:scale-[.97]"
        >
          <ArrowLeft aria-hidden className="h-4 w-4" />
          Atlas
        </button>
        <h1 className="mx-1 mb-3.5 mt-1 font-serif text-display text-ink">Settings</h1>
        {user && (
          <div className={LIST}>
            <div className="flex items-center gap-3 px-4 py-3">
              <Avatar name={user.name || user.email} size="lg" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[15px] font-medium text-ink">{user.name}</div>
                <div className="truncate text-[13px] text-muted-foreground">{user.email}</div>
              </div>
              {user.role && <RolePill role={user.role} />}
            </div>
          </div>
        )}
        {sections.map((s) => (
          <nav key={s.title} aria-label={s.title}>
            <h2 className="mx-2 mb-1.5 mt-5 text-caption uppercase tracking-[0.06em] text-muted-2">
              {s.title}
            </h2>
            <div className={LIST}>
              {s.items.map(({ to, label, icon: Icon, badge }) => (
                <Link key={to} to={to} className={ROW}>
                  <Icon aria-hidden className="h-4 w-4 text-muted-foreground" />
                  <span className="flex-1">{label}</span>
                  {badge && <CountBadge count={badge.count} label={badge.label} className="ml-0" />}
                  <ChevronRight aria-hidden className="h-4 w-4 text-muted-2" />
                </Link>
              ))}
            </div>
          </nav>
        ))}
        <div className={cn(LIST, 'mt-[22px]')}>
          <button type="button" onClick={onSignOut} className={cn(ROW, 'w-full text-negative')}>
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
