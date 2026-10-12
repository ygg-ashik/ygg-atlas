import { useTheme } from '@/lib/theme-provider';
import { Button, ThemeSwitch } from '@/ui';
import { AccountPage, SectionHeading } from './account-page';
import { SettingsGroup, SettingsRow } from './settings-row';

export interface GeneralPageProps {
  /** The signed-in email, from the auth feature (composed in App.tsx). */
  email: string;
  onSignOut: () => void;
}

const SHORTCUTS = [
  { keys: '⌘K', title: 'Search or run a quick action', hint: 'Ctrl+K on Windows and Linux.' },
  { keys: '⌘,', title: 'Open Settings', hint: 'Ctrl+, on Windows and Linux.' },
  { keys: 'Esc', title: 'Back to Atlas', hint: 'From any Settings page; closes a dialog first.' },
];

/** Settings › General: appearance, keyboard shortcuts and the account. */
export function GeneralPage({ email, onSignOut }: GeneralPageProps) {
  const { theme, setTheme } = useTheme();
  return (
    <AccountPage title="General" sub="How Atlas looks, and the keys that get you around.">
      <SectionHeading>Appearance</SectionHeading>
      <SettingsGroup label="Appearance">
        <SettingsRow
          title="Theme"
          hint="System follows your device. The account menu has the same switch."
        >
          <ThemeSwitch value={theme} onChange={setTheme} />
        </SettingsRow>
      </SettingsGroup>
      <SectionHeading>Keyboard</SectionHeading>
      <SettingsGroup label="Keyboard shortcuts">
        {SHORTCUTS.map((s) => (
          <SettingsRow key={s.keys} title={s.title} hint={s.hint}>
            <kbd className="min-w-[44px] rounded-md bg-card-2 px-2 py-1 text-center font-mono text-xs text-ink shadow-[inset_0_0_0_1px_hsl(var(--border)/0.6)]">
              {s.keys}
            </kbd>
          </SettingsRow>
        ))}
      </SettingsGroup>
      <SectionHeading>Account</SectionHeading>
      <SettingsGroup label="Account">
        <SettingsRow
          title="Signed in as"
          hint={<span className="font-mono text-[12.5px]">{email}</span>}
        >
          <Button variant="pill" onClick={onSignOut}>
            Sign out
          </Button>
        </SettingsRow>
      </SettingsGroup>
    </AccountPage>
  );
}
