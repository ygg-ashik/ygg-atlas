import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ConsentApiError,
  getConsentPrompt,
  submitConsent,
  type ConsentPrompt,
} from './consent-api';
import { ConsentPage, type ConsentSession } from '.';

// The real API module pulls in Firebase; only ConsentApiError is used from it here.
vi.mock('@/api/axios-instance', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('./consent-api', async (importActual) => ({
  ...(await importActual<Record<string, unknown>>()),
  getConsentPrompt: vi.fn(),
  submitConsent: vi.fn(),
}));

const TXN = 'txn-0123456789abcdefghij';
const LOOPBACK = 'http://localhost:35535/oauth/callback';
const HOSTED = 'https://claude.ai/api/mcp/auth_callback';

const PROMPT: ConsentPrompt = {
  transaction_id: TXN,
  client_name: 'Claude Code',
  redirect_uri: LOOPBACK,
  redirect_host: 'localhost:35535',
  loopback: true,
  user_email: 'ashik@yougotagift.com',
  eligible: true,
  ineligible_reason: null,
  expires_at: '2026-10-09T10:10:00Z',
};

const HOSTED_PROMPT: ConsentPrompt = {
  ...PROMPT,
  client_name: 'Claude',
  redirect_uri: HOSTED,
  redirect_host: 'claude.ai',
  loopback: false,
};

const prompt = vi.mocked(getConsentPrompt);
const submit = vi.mocked(submitConsent);
const assign = vi.fn<(url: string | URL) => void>();
let session: ConsentSession;

function renderPage(search = `?txn=${TXN}`) {
  render(
    <MemoryRouter initialEntries={[`/oauth/consent${search}`]}>
      <Routes>
        <Route path="/oauth/consent" element={<ConsentPage session={session} />} />
      </Routes>
    </MemoryRouter>,
  );
}

const approve = () => screen.getByRole('button', { name: 'Approve' });
const deny = () => screen.getByRole('button', { name: 'Deny' });

beforeEach(() => {
  session = {
    email: 'ashik@yougotagift.com',
    isLoading: false,
    signIn: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
  };
  prompt.mockReset().mockResolvedValue(PROMPT);
  submit.mockReset();
  assign.mockReset();
  vi.spyOn(window.location, 'assign').mockImplementation(assign);
});

afterEach(() => vi.restoreAllMocks());

describe('ConsentPage', () => {
  it('shows a loading status while the request is checked', () => {
    prompt.mockReturnValue(new Promise(() => undefined));
    renderPage();
    expect(screen.getByRole('status')).toHaveTextContent(/checking/i);
  });

  it('shows client name, user email and redirect host', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(
      'Claude Code wants to access Atlas',
    );
    expect(screen.getByText('ashik@yougotagift.com')).toBeInTheDocument();
    expect(screen.getByText('localhost:35535')).toHaveClass('font-mono');
    expect(screen.getByText(/data you're permitted to see/i)).toBeInTheDocument();
    expect(screen.getByText(/current role and groups/i)).toBeInTheDocument();
    expect(screen.getByText(/disconnect it at any time/i)).toBeInTheDocument();
  });

  it('warns for a loopback redirect', async () => {
    renderPage();
    expect(await screen.findByRole('note')).toHaveTextContent(/runs on your computer/i);
  });

  it('names the host for a hosted redirect', async () => {
    prompt.mockResolvedValue(HOSTED_PROMPT);
    renderPage();
    expect(await screen.findByText(/will send the approval to/i)).toHaveTextContent('claude.ai');
    expect(screen.queryByText(/runs on your computer/i)).toBeNull();
  });

  it('approve submits and navigates to the redirect', async () => {
    submit.mockResolvedValue({ redirect_to: `${LOOPBACK}?code=abc&state=xyz` });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(`${LOOPBACK}?code=abc&state=xyz`));
    expect(submit).toHaveBeenCalledWith(TXN, 'approve');
    expect(await screen.findByText(/authentication successful/i)).toBeInTheDocument();
  });

  it('deny navigates with access_denied', async () => {
    submit.mockResolvedValue({ redirect_to: `${LOOPBACK}?error=access_denied&state=xyz` });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Deny' }));
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith(`${LOOPBACK}?error=access_denied&state=xyz`),
    );
    expect(submit).toHaveBeenCalledWith(TXN, 'deny');
  });

  it('refuses to navigate when redirect_to is not the registered redirect', async () => {
    submit.mockResolvedValue({ redirect_to: 'http://localhost:35535/elsewhere?code=abc' });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it('disables both buttons while submitting', async () => {
    submit.mockReturnValue(new Promise(() => undefined));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(approve()).toBeDisabled());
    expect(deny()).toBeDisabled();
    fireEvent.click(approve());
    expect(submit).toHaveBeenCalledOnce();
  });

  it('ineligible user sees Request access linking to /account/requests/new?kind=role', async () => {
    prompt.mockResolvedValue({ ...PROMPT, eligible: false, ineligible_reason: 'no_mcp_use' });
    renderPage();
    expect(await screen.findByText(/doesn't include MCP access yet/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Request access' })).toHaveAttribute(
      'href',
      '/account/requests/new?kind=role',
    );
    expect(screen.queryByRole('button')).toBeNull();
    expect(assign).not.toHaveBeenCalled();
  });

  it('approve refused for no mcp:use switches to the ineligible page', async () => {
    submit.mockRejectedValue(new ConsentApiError(403, 'no_mcp_use'));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    expect(await screen.findByRole('link', { name: 'Request access' })).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it('expired or used request shows the start-again message', async () => {
    prompt.mockRejectedValue(new ConsentApiError(404, null));
    renderPage();
    expect(await screen.findByText(/expired or was already used/i)).toBeInTheDocument();
    expect(screen.getByText(/start again from your MCP client/i)).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('disabled account sees the disabled message and no buttons', async () => {
    prompt.mockRejectedValue(new ConsentApiError(403, 'user_disabled'));
    renderPage();
    expect(await screen.findByText(/access is disabled/i)).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('non-company account sees the company-account message and no buttons', async () => {
    prompt.mockRejectedValue(new ConsentApiError(403, 'not_company_account'));
    renderPage();
    expect(await screen.findByText(/only accepts @yougotagift\.com/i)).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('never shows a raw error body', async () => {
    prompt.mockRejectedValue(new ConsentApiError(500, null));
    renderPage();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText(/Traceback/)).toBeNull();
  });

  it('signed-out visitor sees Continue with Google and it calls signIn', async () => {
    session.email = null;
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /continue with google/i }));
    await waitFor(() => expect(session.signIn).toHaveBeenCalledOnce());
    expect(prompt).not.toHaveBeenCalled();
  });

  it('explains a failed sign-in inline', async () => {
    session.email = null;
    session.signIn = vi.fn<() => Promise<void>>().mockRejectedValue(new Error('network'));
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /continue with google/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/try again/i);
  });

  it('missing txn shows the incomplete-link message', () => {
    renderPage('');
    expect(screen.getByText(/sign-in link is incomplete/i)).toBeInTheDocument();
    expect(prompt).not.toHaveBeenCalled();
  });

  it('renders on glass', async () => {
    renderPage();
    expect((await screen.findByRole('heading', { level: 1 })).closest('[data-glass]')).not.toBe(
      null,
    );
  });

  it('asks the browser not to send a referrer from this page', async () => {
    renderPage();
    await screen.findByRole('heading', { level: 1 });
    expect(document.head.querySelector('meta[name="referrer"]')).toHaveAttribute(
      'content',
      'no-referrer',
    );
  });
});
