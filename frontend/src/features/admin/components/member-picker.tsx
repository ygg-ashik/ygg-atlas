import { useState } from 'react';
import { Command } from 'cmdk';
import { type User } from '@/api/admin-users';
import { useAdminUsers } from '@/api/hooks/use-admin-users';
import { Avatar, Button, Input, Select } from '@/ui';
import { type GroupStanding } from '@/api/access';
import { useDebouncedValue } from '../hooks/use-debounced-value';

// Same look as the ui `Input` (DESIGN.md › field-input); cmdk needs its own input element.
const SEARCH =
  'w-full rounded-md border border-border bg-card px-3 py-[9px] text-sm text-ink outline-none transition-[border-color,box-shadow] duration-200 placeholder:text-muted-2 focus-visible:border-primary-text focus-visible:ring-4 focus-visible:ring-primary/15';
const ITEM =
  'flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] text-body data-[selected=true]:bg-primary/10 data-[selected=true]:text-ink';

interface MemberPickerProps {
  /** Admin:groups may appoint managers; everyone else adds plain members. */
  canAppoint: boolean;
  onPick: (user: User, standing: GroupStanding) => void;
}

/** Find a person by name or email (server-side search), then stage the add. */
export function MemberPicker({ canAppoint, onPick }: MemberPickerProps) {
  const [query, setQuery] = useState('');
  const [chosen, setChosen] = useState<User | null>(null);
  const [standing, setStanding] = useState<GroupStanding>('member');
  const q = useDebouncedValue(query.trim());
  const results = useAdminUsers(q ? { q } : {});
  const open = !chosen && q !== '';
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
              setQuery('');
            }}
          />
        ) : (
          <Command.Input
            aria-label="Find a person"
            placeholder="Add by name or email"
            value={query}
            onValueChange={setQuery}
            className={SEARCH}
          />
        )}
        {open && (
          <Command.List className="glass absolute inset-x-0 top-[calc(100%+6px)] z-20 max-h-64 overflow-y-auto rounded-shell p-2">
            <Command.Empty className="px-2.5 py-2 text-[13.5px] text-muted-foreground">
              {results.isPending ? 'Searching…' : 'Nobody matches'}
            </Command.Empty>
            {results.items.slice(0, 8).map((u) => (
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
          setQuery('');
        }}
      >
        Add member
      </Button>
    </div>
  );
}
