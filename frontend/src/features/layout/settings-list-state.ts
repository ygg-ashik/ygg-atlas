// src/features/layout/settings-list-state.ts
// Below 600px Settings drills down: `/settings` with this history state shows
// the list of settings pages instead of General, so browser Back returns to it.

export const SETTINGS_LIST_STATE = { settingsList: true } as const;

/** True when the location's state asks for the drill-down list. */
export function wantsSettingsList(state: unknown): boolean {
  return (
    typeof state === 'object' &&
    state !== null &&
    (state as { settingsList?: unknown }).settingsList === true
  );
}
