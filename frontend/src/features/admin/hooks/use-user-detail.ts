import { useParams, useSearchParams } from 'react-router-dom';
import { useUserDetail } from '@/api/hooks/use-admin-users';
import { useMyAccess } from '@/api/hooks/use-my-access';

export const USER_TABS = ['groups', 'grants', 'effective', 'tokens', 'requests'] as const;
export type UserTab = (typeof USER_TABS)[number];

const isTab = (v: string | null): v is UserTab => USER_TABS.includes(v as UserTab);

/** The user detail route: `/settings/admin/users/:id?tab=…`, the user, and whether it is the viewer. */
export function useUserDetailView() {
  const { id = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const raw = params.get('tab');
  const tab: UserTab = isTab(raw) ? raw : 'groups';
  const detail = useUserDetail(id || null);
  const me = useMyAccess();
  const isSelf = !!me.access && me.access.user_id === id;
  const setTab = (next: UserTab) =>
    setParams(next === 'groups' ? {} : { tab: next }, { replace: true });
  return { id, tab, setTab, detail, isSelf };
}
