import { type RequestOptions } from '@/api/access-requests';
import { type RoleInfo } from '@/api/access';
import {
  Button,
  ErrorNotice,
  Field,
  FieldError,
  Input,
  RadioList,
  RolePill,
  SkeletonRegion,
  SkeletonRows,
  Tag,
  type RadioListOption,
} from '@/ui';
import { addedCapabilities, DIRECT, requestableRoles } from '../request-rules';
import { type RequestFormState } from '../hooks/use-request-form';

const LABEL = 'text-label font-medium text-ink';
const HINT = 'text-xs text-muted-foreground';

/** The resource that finds groups (group kind) or is asked for (resource kind). */
export function ResourceField({ form, label }: { form: RequestFormState; label: string }) {
  // A path from a chat link is read-only until "Change"; its URL-supplied label
  // is shown only while the path is still the one the link named.
  const hint = form.locked ? (
    <>
      {label ? `${label} · ` : ''}prefilled from your chat
      {!form.sent && (
        <>
          {' · '}
          <button
            type="button"
            onClick={form.unlock}
            className="font-medium text-primary-text hover:underline"
          >
            Change
          </button>
        </>
      )}
    </>
  ) : (
    'Groups are found by the data they hold, e.g. demo/order/revenue. Press Enter to look it up.'
  );
  return (
    <Field
      label={form.kind === 'resource' ? 'Resource' : 'Data you need'}
      hint={hint}
      error={form.resourceError}
    >
      <Input
        mono
        value={form.resourceDraft}
        disabled={form.sent}
        readOnly={form.locked}
        aria-readonly={form.locked || undefined}
        placeholder="source/entity/item"
        onChange={(e) => form.setResourceDraft(e.target.value)}
        onBlur={form.commitResource}
        onKeyDown={(e) => {
          if (e.key !== 'Enter') return;
          e.preventDefault();
          form.commitResource();
        }}
      />
    </Field>
  );
}

function groupOptions(data: RequestOptions, withDirect: boolean): RadioListOption<string>[] {
  const rows: RadioListOption<string>[] = data.groups.map((g) => ({
    value: g.id,
    title: <span className="font-mono text-[13px]">{g.name}</span>,
    detail: g.managers.length
      ? `Decided by ${g.managers.join(' or ')}`
      : 'No managers · an admin decides',
  }));
  if (withDirect) {
    rows.push({
      value: DIRECT,
      title: 'Direct grant for me only',
      description: data.can_request_resource
        ? 'Decided by an admin. Direct grants usually expire after 90 days.'
        : 'Not needed: your access already covers it.',
      disabled: !data.can_request_resource,
    });
  }
  return rows;
}

/** Groups holding the resource (managers by display name only) and, for the
 * resource kind, a direct grant. */
export function GroupChoices({ form }: { form: RequestFormState }) {
  const { options } = form;
  const resourceKind = form.kind === 'resource';
  const label = resourceKind ? 'Who can approve it' : 'Groups that hold it';
  if (!form.resource) return null;
  if (options.isPending) {
    return (
      <SkeletonRegion label="groups" className="mt-[18px] overflow-hidden rounded-lg bg-card">
        <SkeletonRows count={3} />
      </SkeletonRegion>
    );
  }
  if (options.isError) {
    return (
      <ErrorNotice
        className="mt-[18px]"
        title="Couldn't load the groups that hold it"
        onRetry={() => void options.refetch()}
        retrying={options.isFetching}
      >
        Nothing was sent. Try again in a moment.
      </ErrorNotice>
    );
  }
  const rows = groupOptions(options.data, resourceKind);
  return (
    <div className="mt-[18px] grid gap-1.5">
      <div className={LABEL}>{label}</div>
      {!options.data.can_request_resource && (
        <p className={HINT}>
          You already have access to <span className="font-mono">{options.data.resource}</span>.
        </p>
      )}
      {rows.length ? (
        <>
          <p className={HINT}>
            {resourceKind
              ? 'These groups already hold it. Pick one and its managers decide; or ask for a direct grant.'
              : 'Pick one and its managers decide.'}
          </p>
          <RadioList
            label={label}
            options={rows}
            value={form.choice}
            onChange={form.sent ? () => {} : form.setChoice}
          />
        </>
      ) : (
        <NoHolders form={form} />
      )}
      {form.errors.target && <FieldError>{form.errors.target}</FieldError>}
    </div>
  );
}

function NoHolders({ form }: { form: RequestFormState }) {
  const askDirect = () => {
    form.setKind('resource');
    form.setChoice(DIRECT);
  };
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <p className={HINT}>No group holds this yet.</p>
      {form.kind === 'group' && (
        <Button type="button" variant="pill" size="sm" onClick={askDirect}>
          Ask for a direct grant
        </Button>
      )}
    </div>
  );
}

function roleOptions(roles: readonly RoleInfo[], current: string): RadioListOption<string>[] {
  return requestableRoles(roles, current).map((r) => ({
    value: r.name,
    title: (
      <>
        <RolePill role={r.name} />
        {r.current && <Tag>current</Tag>}
      </>
    ),
    description: r.available ? <Adds caps={addedCapabilities(roles, current, r.name)} /> : null,
    disabled: !r.available,
  }));
}

function Adds({ caps }: { caps: string[] }) {
  if (!caps.length) return null;
  return (
    <>
      Adds{' '}
      {caps.map((c, i) => (
        <span key={c}>
          {i > 0 && ', '}
          <span className="font-mono">{c}</span>
        </span>
      ))}
    </>
  );
}

/** Roles strictly above the caller's; an admin decides. */
export function RoleChoices({ form, current }: { form: RequestFormState; current: string }) {
  const { catalog } = form;
  if (catalog.isPending) {
    return (
      <SkeletonRegion label="roles" className="overflow-hidden rounded-lg bg-card">
        <SkeletonRows count={3} />
      </SkeletonRegion>
    );
  }
  if (catalog.isError) {
    return (
      <ErrorNotice
        title="Couldn't load the roles"
        onRetry={() => void catalog.refetch()}
        retrying={catalog.isFetching}
      >
        Nothing was sent. Try again in a moment.
      </ErrorNotice>
    );
  }
  return (
    <div className="grid gap-1.5">
      <div className={LABEL}>Role</div>
      <p className={HINT}>
        Role requests are decided by an admin. <span>Your role today is</span>{' '}
        <b className="font-medium text-ink">{current}</b>.
      </p>
      <RadioList
        label="Role"
        options={roleOptions(catalog.data.roles, current)}
        value={form.role}
        onChange={form.sent ? () => {} : form.setRole}
      />
      {form.errors.target && <FieldError>{form.errors.target}</FieldError>}
    </div>
  );
}
