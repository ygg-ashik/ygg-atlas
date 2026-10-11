import { useState } from 'react';
import { type User } from '@/api/admin-users';
import {
  useDeleteUserAttribute,
  usePutUserAttribute,
  useUserAttributes,
} from '@/api/hooks/use-row-field';
import { Button, ErrorNotice, Input, SkeletonRegion, SkeletonRows } from '@/ui';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { ATTRIBUTE_DELETE, ATTRIBUTE_SET, attributeLines } from '../review-lines';
import { ReviewSlot } from './review-slot';
import { CARD } from './surfaces';

/** The backend's refusal for editing your own attributes (`_not_self_attribute`). */
const SELF_REFUSAL = "You can't change your own attributes. Ask another admin.";

/** Per-key user attributes: the values `$self` resolves to in row scopes, so
 * every set and removal is reviewed first. The backend validates keys. */
export function AttributesEditor({ user, isSelf }: { user: User; isSelf: boolean }) {
  const attributes = useUserAttributes(user.id);
  const put = usePutUserAttribute();
  const remove = useDeleteUserAttribute();
  const write = useReviewedWrite();
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');
  if (attributes.isPending) {
    return (
      <SkeletonRegion label="attributes" className={`${CARD} mt-3`}>
        <SkeletonRows count={2} />
      </SkeletonRegion>
    );
  }
  if (attributes.isError) {
    return (
      <ErrorNotice
        className="mt-3"
        title="Couldn't load attributes"
        onRetry={() => void attributes.refetch()}
        retrying={attributes.isFetching}
      />
    );
  }
  const rows = attributes.data;
  const before = (k: string) => rows.find((a) => a.key === k)?.value ?? null;
  const stage = (k: string, v: string | null) =>
    write.open({
      slot: 'attr',
      title: v === null ? `Remove attribute ${k}` : `Set attribute ${k}`,
      auditAction: v === null ? ATTRIBUTE_DELETE : ATTRIBUTE_SET,
      lines: attributeLines(user.email, k, before(k), v),
      applyLabel: v === null ? 'Remove attribute' : 'Set attribute',
      run: async () => {
        if (v === null) await remove.mutateAsync({ userId: user.id, key: k });
        else await put.mutateAsync({ userId: user.id, key: k, value: v });
        setKey('');
        setValue('');
      },
    });
  return (
    <section aria-label="Attributes" className={`${CARD} mt-3 px-5 py-4`}>
      <p className="text-label font-medium text-ink">Attributes</p>
      <p className="mb-2.5 text-caption text-muted-foreground">
        A row scope with <span className="font-mono">$self</span> matches these values.
      </p>
      {rows.length === 0 ? (
        <p className="mb-2.5 text-caption text-muted-foreground">No attributes set.</p>
      ) : (
        <div className="mb-2.5 flex flex-wrap gap-1.5">
          {rows.map((a) => (
            <Button
              key={a.key}
              variant="pill"
              size="sm"
              disabled={isSelf}
              aria-label={`Remove ${a.key}`}
              onClick={() => stage(a.key, null)}
            >
              <span className="font-mono">
                {a.key} = {a.value}
              </span>
              {!isSelf && <span aria-hidden>✕</span>}
            </Button>
          ))}
        </div>
      )}
      {isSelf ? (
        <p className="text-caption text-muted-foreground">{SELF_REFUSAL}</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Input
            aria-label="Key"
            className="w-36 font-mono"
            placeholder="country"
            spellCheck={false}
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          <Input
            aria-label="Value"
            className="w-48 font-mono"
            placeholder="AE"
            spellCheck={false}
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
      )}
      <ReviewSlot write={write} slot="attr" />
    </section>
  );
}
