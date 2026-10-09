import { Link } from 'react-router-dom';
import { type RequestKind } from '@/api/access-requests';
import { Button, Field, FieldError, Morph, SegmentedControl, Textarea } from '@/ui';
import { type RequestFormState } from '../hooks/use-request-form';
import { GroupChoices, ResourceField, RoleChoices } from './request-choices';

const KINDS = [
  { value: 'group', label: 'Group' },
  { value: 'role', label: 'Role' },
  { value: 'resource', label: 'Resource' },
] as const satisfies readonly { value: RequestKind; label: string }[];

interface RequestFormProps {
  form: RequestFormState;
  /** Business label of a prefilled resource ("Checkout funnel"). */
  label: string;
  currentRole: string;
}

/** Screen 2 · the request form on a solid card: kind pills, the kind's choice,
 * a required note, and who it goes to. Send morphs to "✓ Sent". */
export function RequestForm({ form, label, currentRole }: RequestFormProps) {
  return (
    <form
      noValidate
      aria-label="Access request"
      onSubmit={(e) => {
        e.preventDefault();
        form.submit();
      }}
      className="rounded-card bg-card px-[22px] py-5 shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_2px_rgba(0,0,0,0.04)]"
    >
      <div className="mb-2 text-label font-medium text-ink">What do you need?</div>
      <SegmentedControl
        kind="radio"
        label="Request kind"
        className="mb-5"
        options={KINDS.map((k) => ({ ...k, disabled: form.sent }))}
        value={form.kind}
        onChange={form.setKind}
      />
      {form.kind === 'role' ? (
        <RoleChoices form={form} current={currentRole} />
      ) : (
        <>
          <ResourceField form={form} label={label} />
          <GroupChoices form={form} />
          {!form.resource && form.errors.target && (
            <div className="mt-2">
              <FieldError>{form.errors.target}</FieldError>
            </div>
          )}
        </>
      )}
      <Field
        className="mt-[18px]"
        label={
          <>
            Why do you need it?{' '}
            <span className="text-caption font-normal text-muted-foreground">required</span>
          </>
        }
        error={form.errors.note}
      >
        <Textarea
          value={form.note}
          disabled={form.sent}
          placeholder="e.g. Reviewing checkout drop-off for the Q4 redesign"
          onChange={(e) => form.setNote(e.target.value)}
        />
      </Field>
      <FormFooter form={form} />
    </form>
  );
}

function FormFooter({ form }: { form: RequestFormState }) {
  return (
    <div className="mt-[18px] flex flex-wrap items-center gap-2.5">
      {form.sent ? (
        <span role="status" className="flex items-center gap-1.5 text-[12.5px] text-positive">
          <span>Sent to {form.approver}.</span>
          <Link to="/account/requests" className="font-medium hover:underline">
            Track it in My requests →
          </Link>
        </span>
      ) : (
        <span className="text-caption text-muted-foreground">Goes to {form.approver}</span>
      )}
      {form.errors.form && <FieldError>{form.errors.form}</FieldError>}
      <span className="flex-1" />
      {!form.sent && (
        <Button asChild variant="pill">
          <Link to="/account">Cancel</Link>
        </Button>
      )}
      <Button
        type="submit"
        disabled={form.sent || form.sending}
        aria-busy={form.sending}
        aria-label={form.sent ? 'Sent' : 'Send request'}
      >
        <Morph done={form.sent} from="Send request" to="✓ Sent" />
      </Button>
    </div>
  );
}
