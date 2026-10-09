import { useState } from 'react';
import { type User } from '@/api/admin-users';
import {
  useDeleteUserAttribute,
  usePutUserAttribute,
  useUserAttributes,
} from '@/api/hooks/use-row-field';
import { Button, FutureControl, Input, Tag } from '@/ui';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { attributeLines } from '../review-lines';
import { ReviewSlot } from './review-slot';
import { CARD } from './surfaces';

/** Phase 3: per-key user attributes (the `$self` values of row scopes). Until
 * the route ships it is shown disabled ("Arrives with row and field controls"). */
export function AttributesEditor({ user }: { user: User }) {
  const attributes = useUserAttributes(user.id);
  const put = usePutUserAttribute();
  const remove = useDeleteUserAttribute();
  const write = useReviewedWrite();
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');
  const data = attributes.data;
  if (!data?.available) {
    return (
      <FutureControl label="Attributes" className="mt-3">
        <Tag mono>country = AE</Tag>
        <Tag mono>team = paid</Tag>
      </FutureControl>
    );
  }
  const before = (k: string) => data.data.find((a) => a.key === k)?.value ?? null;
  const stage = (k: string, v: string | null) =>
    write.open({
      slot: 'attr',
      title: v === null ? `Remove attribute ${k}` : `Set attribute ${k}`,
      auditAction: v === null ? 'attribute.delete' : 'attribute.put',
      lines: attributeLines(user.email, k, before(k), v),
      run: () =>
        v === null
          ? remove.mutateAsync({ userId: user.id, key: k })
          : put.mutateAsync({ userId: user.id, key: k, value: v }),
    });
  return (
    <section aria-label="Attributes" className={`${CARD} mt-3 px-5 py-4`}>
      <p className="mb-2 text-label font-medium text-ink">Attributes</p>
      <div className="mb-2.5 flex flex-wrap gap-1.5">
        {data.data.map((a) => (
          <Button
            key={a.key}
            variant="pill"
            size="sm"
            aria-label={`Remove ${a.key}`}
            onClick={() => stage(a.key, null)}
          >
            <span className="font-mono">
              {a.key} = {a.value}
            </span>
            ✕
          </Button>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Input
          aria-label="Key"
          className="w-36 font-mono"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
        <Input
          aria-label="Value"
          className="w-48 font-mono"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button
          variant="pill"
          disabled={!key.trim() || !value.trim()}
          onClick={() => stage(key.trim(), value.trim())}
        >
          Set
        </Button>
      </div>
      <ReviewSlot write={write} slot="attr" />
    </section>
  );
}
