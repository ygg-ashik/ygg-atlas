// Pure rules for an access request. They mirror the backend's create rules
// (app/access/services/request_rules.py) only to give early, inline feedback: the
// backend decides, and its 422 sentence replaces anything said here.
import { type AccessRequestCreate, type RequestKind } from '@/api/access-requests';
import { type RoleInfo } from '@/api/access';

export const MAX_NOTE = 500;
/** The radio value for "a direct grant for me only" (resource kind). */
export const DIRECT = 'direct';

const KINDS: readonly RequestKind[] = ['group', 'role', 'resource'];
const SEGMENT = /^[a-z0-9_]+$/;

/** Backend `is_resource_path`: 2 or 3 segments of `[a-z0-9_]+` (no patterns). */
export function isResourcePath(path: string): boolean {
  const segments = path.split('/');
  return (segments.length === 2 || segments.length === 3) && segments.every((s) => SEGMENT.test(s));
}

export interface InitialRequest {
  kind: RequestKind;
  resource: string;
  label: string;
}

/** A prefill as it arrives: from the page's query or a dialog opener, untrusted. */
export interface RawPrefill {
  kind?: string | null;
  resource?: string | null;
  label?: string | null;
}

/** The new-request page's `?kind=&resource=&label=`. */
export function prefillFromParams(params: URLSearchParams): RawPrefill {
  return { kind: params.get('kind'), resource: params.get('resource'), label: params.get('label') };
}

/** `kind` (the consent link and guards send `role`) and `resource` + `label` (a
 * chat denial). A resource alone means the resource kind; unknown kinds fall back. */
export function initialRequest(prefill: RawPrefill): InitialRequest {
  const resource = prefill.resource?.trim() ?? '';
  const fallback: RequestKind = resource ? 'resource' : 'group';
  const kind = KINDS.find((k) => k === prefill.kind) ?? fallback;
  return { kind, resource, label: prefill.label?.trim() ?? '' };
}

/** Null when the note is acceptable; otherwise what to do about it. */
export function noteError(note: string, approver: string): string | null {
  if (!note.trim()) return `Add a short note so ${approver} can decide.`;
  if (note.length > MAX_NOTE) return `Keep the note under ${MAX_NOTE} characters.`;
  return null;
}

export interface RoleChoice {
  name: string;
  current: boolean;
  /** Strictly above the current role (backend refuses the rest). */
  available: boolean;
}

function rank(roles: readonly RoleInfo[], role: string): number {
  return roles.findIndex((r) => r.name === role);
}

export function requestableRoles(roles: readonly RoleInfo[], current: string): RoleChoice[] {
  const mine = rank(roles, current);
  return roles.map((r, i) => ({ name: r.name, current: r.name === current, available: i > mine }));
}

/** The first role above `current`, or null at the top. */
export function nextRole(roles: readonly RoleInfo[], current: string): string | null {
  return roles[rank(roles, current) + 1]?.name ?? null;
}

/** Capabilities `target` holds that `current` doesn't. */
export function addedCapabilities(
  roles: readonly RoleInfo[],
  current: string,
  target: string,
): string[] {
  const held = new Set(roles.find((r) => r.name === current)?.capabilities ?? []);
  const wanted = roles.find((r) => r.name === target)?.capabilities ?? [];
  return wanted.filter((c) => !held.has(c));
}

interface GroupManagers {
  id: string;
  managers: string[];
}

/** Who decides the request: the chosen group's managers, otherwise an admin. */
export function approverText(groups: readonly GroupManagers[], choice: string | null): string {
  const managers = groups.find((g) => g.id === choice)?.managers ?? [];
  return managers.length ? managers.join(' and ') : 'an admin';
}

export interface RequestDraft {
  kind: RequestKind;
  resource: string;
  /** A group id or `DIRECT` (group and resource kinds). */
  choice: string | null;
  role: string | null;
  note: string;
}

export interface DraftErrors {
  target?: string;
  note?: string;
}

export type BuiltRequest =
  { ok: true; body: AccessRequestCreate } | { ok: false; errors: DraftErrors };

function target(draft: RequestDraft): { body?: Omit<AccessRequestCreate, 'note'>; error?: string } {
  if (draft.kind === 'role') {
    return draft.role
      ? { body: { kind: 'role', target: draft.role } }
      : { error: 'Pick the role you need.' };
  }
  if (draft.kind === 'resource' && draft.choice === DIRECT) {
    return isResourcePath(draft.resource)
      ? { body: { kind: 'resource', target: draft.resource } }
      : { error: 'Enter one resource path like demo/order/revenue.' };
  }
  if (draft.choice && draft.choice !== DIRECT) {
    return { body: { kind: 'group', target: draft.choice } };
  }
  return {
    error:
      draft.kind === 'group'
        ? 'Pick the group you want to join.'
        : 'Pick a group, or ask for a direct grant.',
  };
}

/** The request body, or every field error at once. A chosen group is always a
 * `group` request (its managers decide); only "direct" asks for the resource. */
export function buildRequest(draft: RequestDraft, approver: string): BuiltRequest {
  const { body, error } = target(draft);
  const note = noteError(draft.note, approver);
  if (!body || note) {
    const errors: DraftErrors = {};
    if (error) errors.target = error;
    if (note) errors.note = note;
    return { ok: false, errors };
  }
  return { ok: true, body: { ...body, note: draft.note.trim() } };
}
