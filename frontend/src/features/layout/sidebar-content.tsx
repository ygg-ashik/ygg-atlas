// src/features/layout/sidebar-content.tsx
import { BrandMark } from '@/ui';
import { AccountMenu, type AccountMenuProps } from './account-menu';
import { NavLinks } from './nav-links';
import { type NavItem } from './types';

export interface SidebarContentProps extends AccountMenuProps {
  nav: readonly NavItem[];
  /** Feature-provided sidebar content (search, chat threads), composed in App.tsx. */
  threads?: React.ReactNode;
}

/** Brand, primary nav, the threads slot and the user chip: nothing else lives in
 * the app sidebar (DESIGN.md › shell-sidebar). Rendered docked (≥1000px) and in
 * the navigation drawer (<1000px). */
export function SidebarContent({ nav, threads, ...account }: SidebarContentProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BrandMark className="px-2.5 pb-3.5 pt-1" />
      <nav className="space-y-0.5" aria-label="Primary">
        <NavLinks items={nav} />
      </nav>
      {threads}
      <div className="mt-auto border-t border-border/60 pt-1.5">
        <AccountMenu {...account} />
      </div>
    </div>
  );
}
