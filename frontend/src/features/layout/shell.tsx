import { Glass } from '@/ui';
import type { ShellUser } from './account-controls';
import { NavDrawer } from './nav-drawer';
import { type NavItem, SidebarContent } from './sidebar-content';

export type { NavItem } from './sidebar-content';

interface ShellProps {
  user: ShellUser | null;
  onSignOut: () => void;
  nav: NavItem[];
  /** Feature-provided sidebar content (e.g. chat threads), composed in App.tsx. */
  threads?: React.ReactNode;
  children: React.ReactNode;
}

/** App frame (DESIGN.md › Layout): 10px inset, floating heavy-glass sidebar,
 * rounded main pane. Below 1000px the sidebar becomes a drawer behind a menu
 * button. Features plug in via props so layout stays decoupled. */
export default function Shell({ user, onSignOut, nav, threads, children }: ShellProps) {
  const sidebar = { user, onSignOut, nav, threads };
  return (
    <div className="flex h-screen gap-2.5 p-2.5">
      <Glass
        as="aside"
        variant="heavy"
        specular
        className="flex w-[236px] shrink-0 flex-col rounded-shell px-2.5 py-3.5 max-[999px]:hidden"
      >
        <SidebarContent {...sidebar} />
      </Glass>
      <NavDrawer {...sidebar} />
      <main className="relative min-w-0 flex-1 overflow-hidden rounded-shell max-[999px]:[--toolbar-lead:58px]">
        {children}
      </main>
    </div>
  );
}
