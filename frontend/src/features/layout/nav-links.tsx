// src/features/layout/nav-links.tsx
import { useId } from 'react';
import { NavLink } from 'react-router-dom';
import { CountBadge, SidebarSectionHeader, cn } from '@/ui';
import { ROUTES } from '@/lib/routes';
import { type NavItem, type NavSection } from './types';

/** Exact-match roots: their children are separate items. */
const EXACT = new Set<string>([ROUTES.home, ROUTES.settings]);

/** Sidebar and rail links: the current one lifts onto a card (DESIGN.md › shell-sidebar). */
export function NavLinks({ items }: { items: readonly NavItem[] }) {
  return (
    <>
      {items.map(({ to, label, icon: Icon, badge, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end ?? EXACT.has(to)}
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

/** A labelled group of links under a `sidebar-section-header`. */
export function TitledSection({ section }: { section: NavSection }) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className="space-y-0.5">
      <SidebarSectionHeader id={id}>{section.title}</SidebarSectionHeader>
      <NavLinks items={section.items} />
    </div>
  );
}
