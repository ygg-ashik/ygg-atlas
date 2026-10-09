// OAuth consent API (backend app/mcp/router.py, plan Task 8). The shared `api` client attaches the
// Firebase bearer, so the grant is bound to the signed-in user, never to anything in the body.
import { isAxiosError } from 'axios';
import { api } from '@/api/axios-instance';

/** GET /api/v1/oauth/consent/{txn} — mirrors ConsentPromptOut. */
export interface ConsentPrompt {
  transaction_id: string;
  client_name: string;
  redirect_uri: string;
  redirect_host: string;
  loopback: boolean;
  user_email: string;
  eligible: boolean;
  ineligible_reason: 'no_mcp_use' | null;
  expires_at: string;
}

export type ConsentDecision = 'approve' | 'deny';

/** POST /api/v1/oauth/consent — mirrors ConsentOut. */
export interface ConsentResult {
  redirect_to: string;
}

/**
 * A failed consent call, reduced to what the page may reason about. `detail` is kept only to
 * classify a 403; it is never rendered (the page shows its own copy).
 */
export class ConsentApiError extends Error {
  constructor(
    readonly status: number | null,
    readonly reason: string | null,
    readonly detail: string | null,
  ) {
    super(`consent request failed (${status ?? 'network'})`);
    this.name = 'ConsentApiError';
  }
}

function field(value: unknown, name: string): unknown {
  return typeof value === 'object' && value !== null
    ? (value as Record<string, unknown>)[name]
    : undefined;
}

function toConsentError(error: unknown): ConsentApiError {
  if (!isAxiosError(error)) return new ConsentApiError(null, null, null);
  const status = error.response?.status ?? null;
  const detail = field(error.response?.data, 'detail');
  if (typeof detail === 'string') return new ConsentApiError(status, null, detail);
  const reason = field(detail, 'reason');
  return new ConsentApiError(status, typeof reason === 'string' ? reason : null, null);
}

export async function getConsentPrompt(txn: string): Promise<ConsentPrompt> {
  try {
    const { data } = await api.get<ConsentPrompt>(`/oauth/consent/${encodeURIComponent(txn)}`);
    return data;
  } catch (error) {
    throw toConsentError(error);
  }
}

export async function submitConsent(
  txn: string,
  decision: ConsentDecision,
): Promise<ConsentResult> {
  try {
    const { data } = await api.post<ConsentResult>('/oauth/consent', {
      transaction_id: txn,
      decision,
    });
    return data;
  } catch (error) {
    throw toConsentError(error);
  }
}
