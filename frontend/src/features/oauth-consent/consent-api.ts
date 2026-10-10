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
 * A failed consent call, reduced to what the page may reason about: the status and, for a 403,
 * the refusal code (backend `ConsentRefusal` in `detail.reason`: no_mcp_use, user_disabled,
 * not_company_account, service_account). Backend text is never read or rendered.
 */
export class ConsentApiError extends Error {
  constructor(
    readonly status: number | null,
    readonly reason: string | null,
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
  if (!isAxiosError(error)) return new ConsentApiError(null, null);
  const status = error.response?.status ?? null;
  const reason = field(field(error.response?.data, 'detail'), 'reason');
  return new ConsentApiError(status, typeof reason === 'string' ? reason : null);
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
