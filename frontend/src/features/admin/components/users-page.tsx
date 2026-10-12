import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';
import { type UserFilters, type UserKind, type UserStatus } from '@/api/admin-users';
import { useAdminUsers } from '@/api/hooks/use-admin-users';
import { useCapabilityCatalog } from '@/api/hooks/use-capability-catalog';
import { useMyAccess } from '@/api/hooks/use-my-access';
import {
  Button,
  DataTable,
  EmptyState,
  ErrorNotice,
  FilterBar,
  Select,
  Skeleton,
  SkeletonRegion,
  SkeletonRows,
} from '@/ui';
import { useDebouncedValue } from '../hooks/use-debounced-value';
import { AdminPage } from './admin-page';
import { userColumns } from './user-row';
import { adminUserPath } from '@/lib/routes';

interface FilterState {
  q: string;
  role: string;
  status: '' | UserStatus;
  kind: '' | UserKind;
}

const NO_FILTERS: FilterState = { q: '', role: '', status: '', kind: '' };

/** Only the set filters go to the API; it does the filtering. */
function toQuery({ q, role, status, kind }: FilterState): UserFilters {
  const out: UserFilters = {};
  if (q.trim()) out.q = q.trim();
  if (role) out.role = role;
  if (status) out.status = status;
  if (kind) out.kind = kind;
  return out;
}

interface PickProps<V extends string> {
  label: string;
  value: V | '';
  options: readonly V[];
  onChange: (value: V | '') => void;
}

function Pick<V extends string>({ label, value, options, onChange }: PickProps<V>) {
  return (
    <Select aria-label={label} value={value} onChange={(e) => onChange(e.target.value as V | '')}>
      <option value="">{label}: any</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </Select>
  );
}

function UsersSkeleton() {
  return (
    <SkeletonRegion label="users" className="rounded-card bg-card px-[18px] py-3.5">
      <Skeleton className="mb-3 h-8 w-1/3" />
      <SkeletonRows count={7} />
    </SkeletonRegion>
  );
}

type UsersList = ReturnType<typeof useAdminUsers>;

interface ResultsProps {
  users: UsersList;
  search: string;
  onClear: () => void;
}

function UsersTable({ users }: { users: UsersList }) {
  const navigate = useNavigate();
  const me = useMyAccess();
  return (
    <>
      <DataTable
        caption="Users"
        columns={userColumns(me.access?.user_id ?? null)}
        rows={users.items}
        rowKey={(u) => u.id}
        rowAction={{
          label: (u) => `Open ${u.display_name || u.email}`,
          onActivate: (u) => navigate(adminUserPath(u.id)),
        }}
      />
      {users.hasNextPage && (
        <div className="mt-3.5 flex justify-center">
          <Button
            variant="pill"
            onClick={() => void users.fetchNextPage()}
            disabled={users.isFetchingNextPage}
          >
            {users.isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}
    </>
  );
}

function UsersResults({ users, search, onClear }: ResultsProps) {
  if (users.isPending) return <UsersSkeleton />;
  if (users.isError) {
    return (
      <ErrorNotice
        title="Couldn't load users"
        onRetry={() => void users.refetch()}
        retrying={users.isFetching}
      >
        The access service didn't answer. Nothing changed.
      </ErrorNotice>
    );
  }
  if (users.items.length > 0) return <UsersTable users={users} />;
  return (
    <EmptyState
      icon={<Search className="h-5 w-5" />}
      title={search ? `No users match “${search}”` : 'No users match these filters'}
      actions={
        <Button variant="pill" onClick={onClear}>
          Clear filters
        </Button>
      }
    >
      Try a shorter search, or clear the role, status and kind filters.
    </EmptyState>
  );
}

/** Screen 6: everyone who has signed in, filtered and keyset-paged by the API. */
export function UsersPage() {
  const [filters, setFilters] = useState<FilterState>(NO_FILTERS);
  const settledQ = useDebouncedValue(filters.q);
  const users = useAdminUsers(toQuery({ ...filters, q: settledQ }));
  const roles = (useCapabilityCatalog().data?.roles ?? []).map((r) => r.name);
  const set = (patch: Partial<FilterState>) => setFilters((f) => ({ ...f, ...patch }));

  return (
    <AdminPage
      title="Users"
      heading="Users"
      sub="Everyone who has signed in, plus service identities. Roles say what people can do; groups say what they can see."
    >
      <FilterBar
        label="Filter users"
        search={{
          value: filters.q,
          onChange: (q) => set({ q }),
          placeholder: 'Search name or email',
          label: 'Search name or email',
        }}
        summary={users.isSuccess ? `${users.items.length} shown` : undefined}
      >
        <Pick
          label="Role"
          value={filters.role}
          options={roles}
          onChange={(role) => set({ role })}
        />
        <Pick<UserStatus>
          label="Status"
          value={filters.status}
          options={['active', 'disabled']}
          onChange={(status) => set({ status })}
        />
        <Pick<UserKind>
          label="Kind"
          value={filters.kind}
          options={['human', 'service']}
          onChange={(kind) => set({ kind })}
        />
      </FilterBar>
      <UsersResults users={users} search={settledQ.trim()} onClear={() => setFilters(NO_FILTERS)} />
    </AdminPage>
  );
}
