// src/features/layout/shell.tsx
import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronLeft } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Glass, cn } from '@/ui';
import { ROUTES, isSettingsPath } from '@/lib/routes';
import { useMediaQuery } from '@/lib/use-media-query';
import { PHONE_QUERY } from './account-menu';
import { NavDrawer } from './nav-drawer';
import { SettingsList } from './settings-list';
import { SETTINGS_LIST_STATE, wantsSettingsList } from './settings-list-state';
import { SettingsRail } from './settings-rail';
import { SidebarContent } from './sidebar-content';
import { type AdminEntry, type NavItem, type NavSection, type ShellUser } from './types';
import { useSettingsHotkeys } from './use-settings-hotkeys';

interface ShellProps {
  user: ShellUser | null;
  onSignOut: () => void;
  /** Primary nav of the app sidebar. */
  nav: readonly NavItem[];
  /** The settings rail's groups, already filtered to what the viewer can open. */
  settings: readonly NavSection[];
  /** The account menu's Admin entry; absent for everyone but managers and admins. */
  admin?: AdminEntry;
  /** Feature-provided sidebar content (e.g. chat threads), composed in App.tsx. */
  threads?: React.ReactNode;
  children: React.ReactNode;
}

type Swap = 'in' | 'back' | null;

/** Which way the sidebar last swapped; null until it first does (no motion on load). */
function useSwap(inSettings: boolean): Swap {
  const [shown, setShown] = useState(inSettings);
  const [swap, setSwap] = useState<Swap>(null);
  if (shown !== inSettings) {
    setShown(inSettings);
    setSwap(inSettings ? 'in' : 'back');
  }
  return swap;
}

/** Docked sidebar: mirrors the `max-[999px]:hidden` breakpoint below. */
const DOCKED_QUERY = '(min-width: 1000px)';

/** After the sidebar swaps, the control that had focus (the chip, a rail link)
 * is gone. Move focus to the new sidebar's entry point (Back to Atlas, or the
 * account chip) when docked, else to the main pane, but only if focus was lost. */
function useSwapFocus(
  swap: Swap,
  inSettings: boolean,
  refs: { aside: React.RefObject<HTMLElement | null>; main: React.RefObject<HTMLElement | null> },
) {
  const docked = useMediaQuery(DOCKED_QUERY, true);
  const { aside, main } = refs;
  useEffect(() => {
    if (!swap) return;
    const lost = !document.activeElement || document.activeElement === document.body;
    if (!lost) return;
    const target = docked ? aside.current?.querySelector<HTMLElement>('[data-swap-focus]') : null;
    (target ?? main.current)?.focus();
  }, [swap, inSettings, docked, aside, main]);
}

/** App frame (DESIGN.md › Layout): 10px inset, floating heavy-glass sidebar,
 * rounded main pane. Inside `/settings` the sidebar swaps in place to the
 * settings rail; ⌘, opens Settings and Escape leaves it. Below 1000px the
 * sidebar is a drawer; below 600px Settings drills down from a list. */
export default function Shell(props: ShellProps) {
  const { user, onSignOut, nav, settings, admin, threads, children } = props;
  const { pathname, search, state } = useLocation();
  const navigate = useNavigate();
  const phone = useMediaQuery(PHONE_QUERY, false);
  const inSettings = isSettingsPath(pathname);
  const swap = useSwap(inSettings);
  const asideRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  useSwapFocus(swap, inSettings, { aside: asideRef, main: mainRef });

  // "Back to Atlas" returns to the last page outside Settings.
  const lastApp = useRef<string>(ROUTES.home);
  useEffect(() => {
    if (!inSettings) lastApp.current = pathname + search;
  }, [inSettings, pathname, search]);
  const back = useCallback(() => navigate(lastApp.current), [navigate]);
  const toList = useCallback(
    () => navigate(ROUTES.settings, { state: SETTINGS_LIST_STATE }),
    [navigate],
  );
  const open = useCallback(
    () => (phone ? toList() : navigate(ROUTES.settings)),
    [phone, toList, navigate],
  );
  useSettingsHotkeys({ inSettings, onOpen: open, onBack: back });

  const sidebar = inSettings ? (
    <SettingsRail sections={settings} email={user?.email ?? null} onBack={back} />
  ) : (
    <SidebarContent nav={nav} threads={threads} user={user} onSignOut={onSignOut} admin={admin} />
  );
  const drillDown = inSettings && phone;
  const showList = drillDown && wantsSettingsList(state);

  return (
    <div className="flex h-screen gap-2.5 p-2.5">
      <Glass
        ref={asideRef}
        as="aside"
        variant="heavy"
        specular
        className="flex w-[236px] shrink-0 flex-col rounded-shell px-2.5 py-3.5 max-[999px]:hidden"
      >
        <div
          key={inSettings ? 'settings' : 'app'}
          className={cn(
            'flex min-h-0 flex-1 flex-col',
            swap === 'in' && 'animate-rail-in',
            swap === 'back' && 'animate-rail-back',
          )}
        >
          {sidebar}
        </div>
      </Glass>
      {drillDown ? !showList && <BackToList onClick={toList} /> : <NavDrawer>{sidebar}</NavDrawer>}
      <main
        ref={mainRef}
        tabIndex={-1}
        className="relative min-w-0 flex-1 overflow-hidden rounded-shell outline-none max-[999px]:[--toolbar-lead:58px]"
      >
        {showList ? (
          <SettingsList sections={settings} user={user} onBack={back} onSignOut={onSignOut} />
        ) : (
          children
        )}
      </main>
    </div>
  );
}

/** Below 600px a settings page leads with a back chevron to the list, where the
 * menu button sits elsewhere (DESIGN.md › settings-drilldown). */
function BackToList({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label="Back to Settings"
      onClick={onClick}
      className="glass fixed left-[30px] top-[28px] z-30 grid h-9 w-9 place-items-center rounded-full text-ink transition-transform duration-100 ease-out active:scale-[.96]"
    >
      <ChevronLeft aria-hidden className="h-5 w-5" />
    </button>
  );
}
