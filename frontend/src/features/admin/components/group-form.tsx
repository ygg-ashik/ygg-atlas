import { useState } from 'react';
import { type Group, type GroupUpdate } from '@/api/admin-groups';
import { useCreateGroup, useUpdateGroup } from '@/api/hooks/use-admin-groups';
import { Button, Field, FieldError, Input, Select, toast, type DiffLine } from '@/ui';
import { subtreeIds } from '../group-tree';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { kv } from '../review-lines';
import { ReviewSlot } from './review-slot';
import { RAISED_CARD } from './surfaces';

interface GroupFormProps {
  /** The group being edited; absent to create one. */
  group?: Group;
  groups: readonly Group[];
  onDone: () => void;
}

const nameOf = (groups: readonly Group[], id: string | null) =>
  groups.find((g) => g.id === id)?.name ?? '—';

/** `group.update` diff: only the fields that change. Moving a group changes what it inherits. */
function updateLines(group: Group, update: GroupUpdate, groups: readonly Group[]): DiffLine[] {
  const lines: DiffLine[] = [{ kind: 'context', text: `group.update  ${group.name}` }];
  const pair = (key: string, before: string, after: string) => {
    lines.push({ kind: 'remove', text: kv(key, before) });
    lines.push({ kind: 'add', text: kv(key, after) });
  };
  if (update.name !== undefined) pair('name', group.name, update.name);
  if (update.description !== undefined) pair('description', group.description, update.description);
  if (update.parent_id !== undefined) {
    pair('parent', nameOf(groups, group.parent_id), nameOf(groups, update.parent_id));
  }
  return lines;
}

function diffOf(group: Group, name: string, description: string, parent: string): GroupUpdate {
  const update: GroupUpdate = {};
  if (name !== group.name) update.name = name;
  if (description !== group.description) update.description = description;
  if ((parent || null) !== group.parent_id) update.parent_id = parent || null;
  return update;
}

/** Create a group, or edit one (edits go through a review card: a move changes inheritance). */
export function GroupForm({ group, groups, onDone }: GroupFormProps) {
  const [name, setName] = useState(group?.name ?? '');
  const [description, setDescription] = useState(group?.description ?? '');
  const [parent, setParent] = useState(group?.parent_id ?? '');
  const create = useCreateGroup();
  const update = useUpdateGroup();
  const write = useReviewedWrite();
  const excluded = group ? subtreeIds(groups, group.id) : [];
  const parents = groups.filter((g) => !excluded.includes(g.id));

  const submit = () => {
    if (!group) {
      void create
        .mutateAsync({ name: name.trim(), description, parent_id: parent || null })
        .then(onDone, () => undefined);
      return;
    }
    const body = diffOf(group, name.trim(), description, parent);
    if (!Object.keys(body).length) return onDone();
    write.open({
      slot: 'group',
      title: `Edit group · ${group.name}`,
      auditAction: 'group.update',
      lines: updateLines(group, body, groups),
      run: async () => {
        await update.mutateAsync({ groupId: group.id, update: body });
        toast.success(`Saved ${body.name ?? group.name}`);
        onDone();
      },
    });
  };

  return (
    <section
      aria-label={group ? 'Edit group' : 'New group'}
      className={`${RAISED_CARD} mb-3 grid gap-3.5 px-5 py-[18px]`}
    >
      <Field label="Name" hint="Lowercase, e.g. marketing-paid">
        <Input value={name} onChange={(e) => setName(e.target.value)} className="font-mono" />
      </Field>
      <Field label="Description">
        <Input value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label="Parent" hint="Members inherit every grant of the parent groups.">
        <Select value={parent} onChange={(e) => setParent(e.target.value)}>
          <option value="">None · top level</option>
          {parents.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </Select>
      </Field>
      {create.errorInfo && <FieldError>{create.errorInfo.message}</FieldError>}
      <div className="flex justify-end gap-2">
        <Button variant="pill" onClick={onDone}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={!name.trim() || create.isPending}>
          {group ? 'Review change' : 'Create group'}
        </Button>
      </div>
      <ReviewSlot write={write} slot="group" />
    </section>
  );
}
