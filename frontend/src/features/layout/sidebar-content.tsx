// src/features/layout/sidebar-content.tsx
import { useId } from 'react';
import type { LucideIcon } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { BrandMark, CountBadge, SidebarSectionHeader, cn } from '@/ui';
import { type AccountMenuItem, type ShellUser, UserMenu } from './account-controls';

export interface NavBadge {
  count: number;
  /** What is counted, for screen readers: "pending requests". */
  label: string;
}

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Section header the item sits under ("Account", "Admin"); none = primary nav. */
  section?: string;
  badge?: NavBadge;
  /** Active only on this exact path (`/` always is). */
  end?: boolean;
}

export interface SidebarContentProps {
  user: ShellUser | null;
  onSignOut: () => void;
  nav: NavItem[];
  /** Links offered in the account menu, composed in App.tsx. */
  menuItems?: AccountMenuItem[];
  /** Feature-provided sidebar content (e.g. chat threads), composed in App.tsx. */
  threads?: React.ReactNode;
}

interface NavSection {
  title: string | undefined;
  items: NavItem[];
}

/** Primary items first, then each section in the order it first appears. */
function sectionsOf(nav: NavItem[]): NavSection[] {
  const sections: NavSection[] = [{ title: undefined, items: [] }];
  for (const item of nav) {
    let section = sections.find((s) => s.title === item.section);
    if (!section) {
      section = { title: item.section, items: [] };
      sections.push(section);
    }
    section.items.push(item);
  }
  return sections.filter((s) => s.items.length > 0);
}

/** Brand, primary nav, the threads slot and the account row. Rendered by the
 * docked sidebar (≥1000px) and by the navigation drawer (<1000px). */
export function SidebarContent({ user, onSignOut, nav, menuItems, threads }: SidebarContentProps) {
  const sections = sectionsOf(nav);
  return (
    <>
      <BrandMark className="px-2.5 pb-3.5 pt-1" />
      <nav className="space-y-0.5" aria-label="Primary">
        {sections.map((s) =>
          s.title ? (
            <TitledSection key={s.title} title={s.title} items={s.items} />
          ) : (
            <NavLinks key="primary" items={s.items} />
          ),
        )}
      </nav>
      {threads}
      <div className="mt-auto border-t border-border/60 pt-1.5">
        <UserMenu user={user} onSignOut={onSignOut} items={menuItems} />
      </div>
    </>
  );
}

function TitledSection({ title, items }: { title: string; items: NavItem[] }) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className="space-y-0.5">
      <SidebarSectionHeader id={id}>{title}</SidebarSectionHeader>
      <NavLinks items={items} />
    </div>
  );
}

function NavLinks({ items }: { items: NavItem[] }) {
  return (
    <>
      {items.map(({ to, label, icon: Icon, badge, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end ?? to === '/'}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-[background-color,transform] duration-200 active:scale-[.97]',
              isActive
                ? 'bg-card text-ink shadow-[0_0_0_1px_hsl(var(--border)),0_1px_3px_rgba(0,0,0,0.06)]'
                : 'text-body hover:bg-foreground/5',
            )
          }
        >
          <Icon aria-hidden className="h-4 w-4 opacity-75" />
          {label}
          {badge && <CountBadge count={badge.count} label={badge.label} />}
        </NavLink>
      ))}
    </>
  );
}
