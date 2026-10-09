import { useState } from 'react';
import { Command } from 'cmdk';
import { Link } from 'react-router-dom';
import { type GroupStanding } from '@/api/access';
import { CANDIDATE_QUERY_MAX, CANDIDATE_QUERY_MIN } from '@/api/admin-groups';
import { useMemberCandidates } from '@/api/hooks/use-admin-groups';
import { useAdminUsers } from '@/api/hooks/use-admin-users';
import { describeMutationError } from '@/api/mutation-errors';
import { Avatar, Button, Input, Select } from '@/ui';
import { useDebouncedValue } from '../hooks/use-debounced-value';

// Same look as the ui `Input` (DESIGN.md › field-input); cmdk needs its own input element.
const SEARCH =
  'w-full rounded-md border border-border bg-card px-3 py-[9px] text-sm text-ink outline-none transition-[border-color,box-shadow] duration-200 placeholder:text-muted-2 focus-visible:border-primary-text focus-visible:ring-4 focus-visible:ring-primary/15';
const ITEM =
  'flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] text-body data-[selected=true]:bg-primary/10 data-[selected=true]:text-ink';
const MAX_SHOWN = 10;

/** Someone the picker can add: a `User` row or a `MemberCandidate`. */
export interface PickedPerson {
  id: string;
  email: string;
  display_name: string;
}

/** Where the search runs. `users`: `GET /admin/users` (admin:users; any user,
 * so an admin can also change an existing member's standing). `candidates`:
 * `GET /admin/groups/{id}/member-candidates` (the group's managers; active
 * humans not yet in the group, 3+ characters). The backend decides either way. */
export type PickerSource = 'users' | 'candidates';

interface MemberPickerProps {
  groupId: string;
  source: PickerSource;
  /** Admin:groups may appoint managers; everyone else adds plain members. */
  canAppoint: boolean;
  onPick: (person: PickedPerson, standing: GroupStanding) => void;
}

/** Find a person by name or email (server-side search), then stage the add. */
export function MemberPicker(props: MemberPickerProps) {
  return props.source === 'users' ? <UserSearch {...props} /> : <CandidateSearch {...props} />;
}

interface SearchResults {
  people: readonly PickedPerson[];
  /** Shown when nothing is listed: searching, too short, nobody, a failure. */
  empty: string;
}

/** The typed text and its debounced, trimmed value (one query per pause). */
function useSearchText() {
  const [text, setText] = useState('');
  const query = useDebouncedValue(text.trim());
  return { text, setText, query };
}

function UserSearch(props: MemberPickerProps) {
  const search = useSearchText();
  const results = useAdminUsers(search.query ? { q: search.query } : {});
  const people = results.items.map((u) => ({
    id: u.id,
    email: u.email,
    display_name: u.display_name,
  }));
  let empty = 'Nobody matches';
  if (results.isPending) empty = 'Searching…';
  else if (results.isError) empty = describeMutationError(results.error).message;
  return <PickerShell {...props} {...search} results={{ people, empty }} />;
}

function CandidateSearch(props: MemberPickerProps) {
  const search = useSearchText();
  const results = useMemberCandidates(props.groupId, search.query);
  const short = search.query.length < CANDIDATE_QUERY_MIN;
  const info = results.isError ? describeMutationError(results.error) : null;
  // Not a member-admin of this group: the backend said 403, so hide the picker
  // and say why (fails closed; the UI never guesses authority).
  if (info?.kind === 'forbidden') return <PickerDenied sentence={info.message} />;
  const people = (results.data ?? []).map((c) => ({
    id: c.user_id,
    email: c.email,
    display_name: c.display_name,
  }));
  let empty = 'Nobody matches who could join';
  if (short) empty = `Type at least ${CANDIDATE_QUERY_MIN} characters of a name or email`;
  else if (results.isPending) empty = 'Searching…';
  else if (info) empty = info.message;
  return (
    <PickerShell
      {...props}
      {...search}
      maxLength={CANDIDATE_QUERY_MAX}
      results={{ people: short ? [] : people, empty }}
    />
  );
}

interface ShellProps extends MemberPickerProps, ReturnType<typeof useSearchText> {
  results: SearchResults;
  maxLength?: number;
}

function PickerShell({ canAppoint, onPick, text, setText, query, results, maxLength }: ShellProps) {
  const [chosen, setChosen] = useState<PickedPerson | null>(null);
  const [standing, setStanding] = useState<GroupStanding>('member');
  const open = !chosen && query !== '';
  return (
    <div className="mb-2.5 flex flex-wrap items-start gap-2">
      <Command
        label="Find a person"
        shouldFilter={false}
        className="relative min-w-[240px] max-w-[340px] flex-1"
      >
        {chosen ? (
          <Input
            aria-label="Find a person"
            readOnly
            value={chosen.email}
            onFocus={() => {
              setChosen(null);
              setText('');
            }}
          />
        ) : (
          <Command.Input
            aria-label="Find a person"
            placeholder="Add by name or email"
            value={text}
            maxLength={maxLength}
            onValueChange={setText}
            className={SEARCH}
          />
        )}
        {open && (
          <Command.List className="glass absolute inset-x-0 top-[calc(100%+6px)] z-20 max-h-64 overflow-y-auto rounded-shell p-2">
            <Command.Empty className="px-2.5 py-2 text-[13.5px] text-muted-foreground">
              {results.empty}
            </Command.Empty>
            {results.people.slice(0, MAX_SHOWN).map((u) => (
              <Command.Item key={u.id} value={u.id} onSelect={() => setChosen(u)} className={ITEM}>
                <Avatar name={u.display_name || u.email} />
                <span className="min-w-0 truncate">{u.display_name}</span>
                <span className="ml-auto truncate text-caption text-muted-foreground">
                  {u.email}
                </span>
              </Command.Item>
            ))}
          </Command.List>
        )}
      </Command>
      {canAppoint && (
        <Select
          aria-label="Standing"
          value={standing}
          onChange={(e) => setStanding(e.target.value as GroupStanding)}
        >
          <option value="member">member</option>
          <option value="manager">manager</option>
        </Select>
      )}
      <Button
        variant="pill"
        disabled={!chosen}
        onClick={() => {
          if (!chosen) return;
          onPick(chosen, canAppoint ? standing : 'member');
          setChosen(null);
          setText('');
        }}
      >
        Add member
      </Button>
    </div>
  );
}

/** The picker's place when the viewer may not add people here. */
export function PickerDenied({ sentence }: { sentence?: string }) {
  return (
    <p className="mb-2.5 text-caption text-muted-foreground">
      {sentence ? `${sentence} ` : ''}People join through their access requests, which you decide in{' '}
      <Link to="/admin/requests" className="text-primary-text underline-offset-4 hover:underline">
        Access requests
      </Link>
      .
    </p>
  );
}
