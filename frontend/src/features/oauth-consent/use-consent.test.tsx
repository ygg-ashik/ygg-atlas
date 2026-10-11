import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ConsentApiError,
  getConsentPrompt,
  submitConsent,
  type ConsentPrompt,
} from './consent-api';
import { useConsent } from './use-consent';
import type { ConsentSession } from './consent-page';

// The real API module pulls in Firebase; only ConsentApiError is used from it here.
vi.mock('@/api/axios-instance', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('./consent-api', async (importActual) => ({
  ...(await importActual<Record<string, unknown>>()),
  getConsentPrompt: vi.fn(),
  submitConsent: vi.fn(),
}));

const TXN = 'txn-0123456789abcdefghij';

const PROMPT: ConsentPrompt = {
  transaction_id: TXN,
  client_name: 'Claude Code',
  redirect_uri: 'http://localhost:35535/oauth/callback',
  redirect_host: 'localhost:35535',
  loopback: true,
  user_email: 'ashik@yougotagift.com',
  eligible: true,
  ineligible_reason: null,
  expires_at: '2026-10-09T10:10:00Z',
};

const session = (over: Partial<ConsentSession> = {}): ConsentSession => ({
  email: 'ashik@yougotagift.com',
  isLoading: false,
  signIn: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
  ...over,
});

const prompt = vi.mocked(getConsentPrompt);
const submit = vi.mocked(submitConsent);
const assign = vi.fn<(url: string | URL) => void>();

beforeEach(() => {
  prompt.mockReset();
  submit.mockReset();
  assign.mockReset();
  vi.spyOn(window.location, 'assign').mockImplementation(assign);
});

afterEach(() => vi.restoreAllMocks());

describe('useConsent', () => {
  it('reports a missing txn without calling the API', () => {
    const { result } = renderHook(() => useConsent(null, session()));
    expect(result.current.state).toEqual({ kind: 'missing-txn' });
    expect(prompt).not.toHaveBeenCalled();
  });

  it('waits for the session check before fetching', () => {
    const { result } = renderHook(() => useConsent(TXN, session({ isLoading: true })));
    expect(result.current.state).toEqual({ kind: 'loading' });
    expect(prompt).not.toHaveBeenCalled();
  });

  it('asks a signed-out visitor to sign in', () => {
    const { result } = renderHook(() => useConsent(TXN, session({ email: null })));
    expect(result.current.state).toEqual({ kind: 'sign-in' });
    expect(prompt).not.toHaveBeenCalled();
  });

  it('eligible prompt → ready', async () => {
    prompt.mockResolvedValue(PROMPT);
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state).toEqual({ kind: 'ready', prompt: PROMPT }));
    expect(prompt).toHaveBeenCalledWith(TXN);
  });

  it('no_mcp_use prompt → ineligible', async () => {
    const p = { ...PROMPT, eligible: false, ineligible_reason: 'no_mcp_use' as const };
    prompt.mockResolvedValue(p);
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state).toEqual({ kind: 'ineligible', prompt: p }));
  });

  it('401 → sign-in', async () => {
    prompt.mockRejectedValue(new ConsentApiError(401, null));
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state).toEqual({ kind: 'sign-in' }));
  });

  it('signing in again after a 401 re-checks the request', async () => {
    const s = session();
    prompt.mockRejectedValueOnce(new ConsentApiError(401, null)).mockResolvedValue(PROMPT);
    const { result } = renderHook(() => useConsent(TXN, s));
    await waitFor(() => expect(result.current.state).toEqual({ kind: 'sign-in' }));
    await act(() => result.current.signIn());
    expect(s.signIn).toHaveBeenCalledOnce();
    await waitFor(() => expect(result.current.state).toEqual({ kind: 'ready', prompt: PROMPT }));
  });

  it('404 → expired', async () => {
    prompt.mockRejectedValue(new ConsentApiError(404, null));
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state).toEqual({ kind: 'expired' }));
  });

  it('403 user_disabled → blocked with our own copy', async () => {
    prompt.mockRejectedValue(new ConsentApiError(403, 'user_disabled'));
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state.kind).toBe('blocked'));
    expect(result.current.state).toEqual({
      kind: 'blocked',
      message: 'Your Atlas access is disabled. Contact an Atlas admin.',
    });
  });

  it('403 not_company_account → blocked with the company-account copy', async () => {
    prompt.mockRejectedValue(new ConsentApiError(403, 'not_company_account'));
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state.kind).toBe('blocked'));
    expect(result.current.state).toEqual({
      kind: 'blocked',
      message: 'Atlas only accepts @yougotagift.com Google accounts.',
    });
  });

  it('403 service_account → blocked with the service-account copy', async () => {
    prompt.mockRejectedValue(new ConsentApiError(403, 'service_account'));
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state.kind).toBe('blocked'));
    expect(result.current.state).toEqual({
      kind: 'blocked',
      message: 'Service accounts use tokens, not sign-in. Sign in with your own Google account.',
    });
  });

  it.each([null, 'something_new', '<script>secret internals</script>'])(
    'a 403 with an unknown code (%s) → the fixed fallback copy',
    async (reason) => {
      prompt.mockRejectedValue(new ConsentApiError(403, reason));
      const { result } = renderHook(() => useConsent(TXN, session()));
      await waitFor(() => expect(result.current.state.kind).toBe('blocked'));
      expect(result.current.state).toEqual({
        kind: 'blocked',
        message: "This account can't approve MCP access. Contact an Atlas admin.",
      });
    },
  );

  it('an unexpected failure → a generic error', async () => {
    prompt.mockRejectedValue(new ConsentApiError(500, null));
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state.kind).toBe('error'));
    expect(JSON.stringify(result.current.state)).not.toMatch(/Traceback/);
  });

  it('approve navigates to the registered redirect', async () => {
    prompt.mockResolvedValue(PROMPT);
    submit.mockResolvedValue({ redirect_to: `${PROMPT.redirect_uri}?code=c&state=s` });
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state.kind).toBe('ready'));
    await act(() => result.current.decide('approve'));
    expect(submit).toHaveBeenCalledWith(TXN, 'approve');
    expect(assign).toHaveBeenCalledWith(`${PROMPT.redirect_uri}?code=c&state=s`);
    expect(result.current.state).toEqual({ kind: 'done', decision: 'approve' });
  });

  it('approve 403 no_mcp_use → ineligible, no navigation', async () => {
    prompt.mockResolvedValue(PROMPT);
    submit.mockRejectedValue(new ConsentApiError(403, 'no_mcp_use'));
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state.kind).toBe('ready'));
    await act(() => result.current.decide('approve'));
    expect(result.current.state).toEqual({ kind: 'ineligible', prompt: PROMPT });
    expect(assign).not.toHaveBeenCalled();
  });

  it('approve 404 → expired', async () => {
    prompt.mockResolvedValue(PROMPT);
    submit.mockRejectedValue(new ConsentApiError(404, null));
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state.kind).toBe('ready'));
    await act(() => result.current.decide('approve'));
    expect(result.current.state).toEqual({ kind: 'expired' });
  });

  it('refuses a redirect_to that is not the registered redirect', async () => {
    prompt.mockResolvedValue(PROMPT);
    submit.mockResolvedValue({ redirect_to: 'https://evil.example/oauth/callback?code=c' });
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state.kind).toBe('ready'));
    await act(() => result.current.decide('approve'));
    expect(assign).not.toHaveBeenCalled();
    expect(result.current.state.kind).toBe('error');
  });

  it('ignores a second decision while the first is in flight', async () => {
    prompt.mockResolvedValue(PROMPT);
    let release: (v: { redirect_to: string }) => void = () => undefined;
    submit.mockReturnValue(new Promise((resolve) => (release = resolve)));
    const { result } = renderHook(() => useConsent(TXN, session()));
    await waitFor(() => expect(result.current.state.kind).toBe('ready'));
    let first: Promise<void> = Promise.resolve();
    act(() => {
      first = result.current.decide('approve');
      void result.current.decide('deny');
    });
    expect(result.current.submitting).toBe(true);
    await act(async () => {
      release({ redirect_to: `${PROMPT.redirect_uri}?code=c` });
      await first;
    });
    expect(submit).toHaveBeenCalledTimes(1);
  });
});
