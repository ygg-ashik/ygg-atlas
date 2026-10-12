import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { type AccessRequestCreate, type RequestKind } from '@/api/access-requests';
import { useCreateRequest, useRequestOptions } from '@/api/hooks/use-access-requests';
import { useCapabilityCatalog } from '@/api/hooks/use-capability-catalog';
import { describeMutationError, type MutationErrorInfo } from '@/api/mutation-errors';
import { actionToast } from '@/ui';
import {
  approverText,
  buildRequest,
  isResourcePath,
  nextRole,
  type DraftErrors,
  type InitialRequest,
} from '../request-rules';
import { ROUTES } from '@/lib/routes';

const BAD_PATH = 'Enter one resource path like demo/order/revenue.';
/** The backend's blank-note sentence (requests.py); it belongs under the note. */
const NOTE_SENTENCE = 'Say why you need this access.';

export interface FormErrors extends DraftErrors {
  /** Not about one field (e.g. the pending-request cap, a network failure). */
  form?: string;
}

/** Where a failed create's sentence belongs. 422s are the backend's validation
 * of the target or the note; anything else is about the whole form. */
function placeError(info: MutationErrorInfo): FormErrors {
  if (info.kind !== 'invalid') return { form: info.message };
  if (info.message === NOTE_SENTENCE) return { note: info.message };
  if (/pending requests/.test(info.message)) return { form: info.message };
  return { target: info.message };
}

/** State of the new-request form: kind, the resource that finds groups, the
 * chosen group / direct / role, the note, and the create mutation. */
export function useRequestForm(initial: InitialRequest, currentRole: string) {
  const navigate = useNavigate();
  const [kind, setKindState] = useState<RequestKind>(initial.kind);
  const [resourceDraft, setResourceDraft] = useState(initial.resource);
  const prefilled = isResourcePath(initial.resource) ? initial.resource : '';
  const [resource, setResource] = useState(prefilled);
  /** A valid path from the link stays read-only until the user chooses to change it. */
  const [locked, setLocked] = useState(prefilled !== '');
  const [resourceError, setResourceError] = useState<string | null>(
    initial.resource && !prefilled ? BAD_PATH : null,
  );
  const [choice, setChoiceState] = useState<string | null>(null);
  const [role, setRoleState] = useState<string | null>(null);
  const [note, setNoteState] = useState('');
  const [errors, setErrors] = useState<FormErrors>({});

  const catalog = useCapabilityCatalog();
  const options = useRequestOptions(kind === 'role' || !resource ? null : resource);
  const create = useCreateRequest();

  const groups = options.data?.groups ?? [];
  const roles = catalog.data?.roles ?? [];
  const chosenRole = role ?? nextRole(roles, currentRole);
  const approver = kind === 'role' ? 'an admin' : approverText(groups, choice);

  const setKind = (next: RequestKind) => {
    setKindState(next);
    setChoiceState(null);
    setErrors({});
  };
  const setChoice = (value: string) => {
    setChoiceState(value);
    setErrors(({ target: _gone, ...rest }) => rest);
  };
  const setRole = (value: string) => {
    setRoleState(value);
    setErrors(({ target: _gone, ...rest }) => rest);
  };
  const setNote = (value: string) => {
    setNoteState(value);
    setErrors(({ note: _gone, ...rest }) => rest);
  };
  const unlock = () => setLocked(false);
  /** Look the resource up (blur or Enter); only a full path is sent. */
  const commitResource = () => {
    const path = resourceDraft.trim();
    if (path === resource) return;
    setChoiceState(null);
    if (isResourcePath(path)) {
      setResource(path);
      setResourceError(null);
    } else {
      setResource('');
      setResourceError(path ? BAD_PATH : null);
    }
  };

  const send = (body: AccessRequestCreate) =>
    create.mutate(body, {
      onError: (error) => {
        const info = describeMutationError(error);
        if (info.kind === 'conflict') {
          actionToast(info.message, {
            actionLabel: 'View',
            onAction: () => navigate(ROUTES.requests),
          });
          return;
        }
        setErrors(placeError(info));
      },
    });

  const submit = () => {
    const built = buildRequest({ kind, resource, choice, role: chosenRole, note }, approver);
    if (!built.ok) {
      setErrors(built.errors);
      return;
    }
    setErrors({});
    send(built.body);
  };

  return {
    kind,
    setKind,
    resourceDraft,
    setResourceDraft,
    commitResource,
    resource,
    resourceError,
    locked,
    unlock,
    options,
    choice,
    setChoice,
    catalog,
    role: chosenRole,
    setRole,
    note,
    setNote,
    approver,
    errors,
    submit,
    sending: create.isPending,
    sent: create.isSuccess,
  };
}

export type RequestFormState = ReturnType<typeof useRequestForm>;
