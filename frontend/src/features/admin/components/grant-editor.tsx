import { useState } from 'react';
import { X } from 'lucide-react';
import { type GrantCreate, type RowScope, type SubjectType } from '@/api/admin-groups';
import { useCreateGrant } from '@/api/hooks/use-admin-grants';
import { useScopeDimensions } from '@/api/hooks/use-row-field';
import { Button, Field, Input, Tag } from '@/ui';
import {
  expiryToIso,
  plusDays,
  todayUtc,
  validateGrantDraft,
  type GrantDraft,
  type GrantDraftErrors,
} from '../grant-rules';
import { useReviewedWrite } from '../hooks/use-reviewed-write';
import { grantCreateLines } from '../review-lines';
import { CatalogPicker } from './catalog-picker';
import { ClearancePicker } from './clearance-picker';
import { DenyConfirm, EffectField, ExpiryField } from './grant-editor-fields';
import { ReviewSlot } from './review-slot';
import { RowScopeBuilder } from './row-scope-builder';
import { RAISED_CARD } from './surfaces';

export interface GrantEditorProps {
  subject: { type: SubjectType; id: string; label: string };
  /** Context line for the review, e.g. "reaches 5 members + marketing-paid". */
  reach?: string;
  /** Who a deny restricts, e.g. "Everyone in marketing and its subgroups". */
  denyNotice?: string;
  restrictCount?: number;
  onClose: () => void;
}

function toCreate(
  subject: GrantEditorProps['subject'],
  d: GrantDraft,
  scope: RowScope | null,
): GrantCreate {
  const body: GrantCreate = {
    subject_type: subject.type,
    subject_id: subject.id,
    effect: d.effect,
    target_kind: d.targetKind,
    target: d.target,
    reason: d.reason.trim(),
    expires_at: expiryToIso(d.expiry),
  };
  // The backend refuses a row scope anywhere but on a resource allow.
  if (scope && d.targetKind === 'resource' && d.effect === 'allow') body.row_scope = scope;
  return body;
}

/** Add a grant: catalog target, effect, expiry, reason; staged as a review card. */
export function GrantEditor({
  subject,
  reach,
  denyNotice,
  restrictCount,
  onClose,
}: GrantEditorProps) {
  const today = todayUtc();
  const preset = plusDays(today, 90);
  const [draft, setDraft] = useState<GrantDraft>({
    subjectType: subject.type,
    targetKind: 'resource',
    target: '',
    effect: 'allow',
    expiry: preset,
    reason: '',
    denyConfirmed: false,
  });
  const [scope, setScope] = useState<RowScope | null>(null);
  const [errors, setErrors] = useState<GrantDraftErrors>({});
  const write = useReviewedWrite();
  const create = useCreateGrant();
  const set = (patch: Partial<GrantDraft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    write.dismiss();
  };
  const user = subject.type === 'user';
  const scoped = draft.targetKind === 'resource' && draft.effect === 'allow';
  // Fail closed: until the dimensions load, a resource allow could only be all rows.
  const scopeReady = useScopeDimensions().isSuccess || !scoped;

  const stage = () => {
    const found = validateGrantDraft(draft, today);
    setErrors(found);
    if (Object.keys(found).length) return;
    const body = toCreate(subject, draft, scope);
    write.open({
      slot: 'grant',
      title: `Add grant · ${subject.label}`,
      auditAction: 'grant.create',
      lines: grantCreateLines(
        subject.label,
        {
          effect: draft.effect,
          target_kind: draft.targetKind,
          target: draft.target,
          reason: draft.reason.trim(),
          expires_at: body.expires_at ?? null,
          row_scope: body.row_scope ?? null,
        },
        reach,
      ),
      applyLabel: 'Apply grant',
      // A create's 409 is usually "That grant already exists.": final, so no Retry.
      retryOn409: false,
      run: () => create.mutateAsync(body),
    });
  };

  return (
    <section aria-label="Grant editor" className={`${RAISED_CARD} mt-3 px-5 py-[18px]`}>
      <div className="flex items-center gap-2">
        <h3 className="font-serif text-title text-ink">Add grant</h3>
        <Tag mono>subject {subject.label}</Tag>
        <Button
          variant="ghost"
          size="icon"
          className="ml-auto"
          aria-label="Close"
          onClick={onClose}
        >
          <X />
        </Button>
      </div>
      {draft.targetKind === 'resource' && (
        <div className="mt-3.5">
          <CatalogPicker
            value={draft.target}
            onChange={(target) => set({ target })}
            error={errors.target}
          />
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-start gap-[18px]">
        <EffectField
          value={draft.effect}
          onChange={(effect) => set({ effect, denyConfirmed: false })}
        />
        <ExpiryField
          value={draft.expiry}
          onChange={(expiry) => set({ expiry })}
          preset={preset}
          error={errors.expiry}
        />
      </div>
      {draft.effect === 'deny' && (
        <DenyConfirm
          who={denyNotice ?? 'This user'}
          target={draft.target}
          count={restrictCount}
          checked={draft.denyConfirmed}
          onChange={(denyConfirmed) => set({ denyConfirmed })}
        />
      )}
      <Field
        className="mt-4"
        label="Reason"
        hint={
          user
            ? 'Required for direct user grants · shown in the audit log'
            : 'Optional for group grants · shown in the audit log'
        }
        error={errors.reason}
      >
        <Input
          value={draft.reason}
          placeholder="e.g. Paid funnel optimisation"
          onChange={(e) => set({ reason: e.target.value })}
        />
      </Field>
      <div className="mt-4 grid gap-3 min-[700px]:grid-cols-2">
        <RowScopeBuilder value={scope} onChange={setScope} applies={scoped} />
        <ClearancePicker
          value={draft.targetKind === 'clearance' ? draft.target : null}
          onChange={(code) =>
            set(
              code
                ? { targetKind: 'clearance', target: code }
                : { targetKind: 'resource', target: '' },
            )
          }
        />
      </div>
      <div className="mt-[18px] flex flex-wrap items-center gap-2">
        <span className="text-caption text-muted-foreground">
          Nothing is written until you approve the review.
        </span>
        <Button variant="pill" className="ml-auto" onClick={onClose}>
          Cancel
        </Button>
        <Button
          onClick={stage}
          disabled={
            !draft.target || !scopeReady || (draft.effect === 'deny' && !draft.denyConfirmed)
          }
        >
          Review change
        </Button>
      </div>
      <ReviewSlot write={write} slot="grant" />
    </section>
  );
}
