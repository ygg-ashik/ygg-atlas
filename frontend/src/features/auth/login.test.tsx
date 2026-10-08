import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LoginPage from './login';

const auth = {
  isAuthenticated: false,
  isLoading: false,
  signInWithGoogle: vi.fn<() => Promise<void>>(),
};

vi.mock('./auth-context', () => ({ useAuth: () => auth }));

function renderLogin() {
  render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<p>home</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

const signInButton = () => screen.getByRole('button', { name: /continue with google/i });

beforeEach(() => {
  auth.isAuthenticated = false;
  auth.isLoading = false;
  auth.signInWithGoogle.mockReset().mockResolvedValue(undefined);
});

describe('LoginPage', () => {
  it('shows the Atlas sign-in panel on glass', () => {
    renderLogin();
    expect(screen.getByText('Atlas')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(signInButton()).toBeEnabled();
    expect(screen.getByText(/@yougotagift\.com/)).toBeInTheDocument();
    expect(signInButton().closest('[data-glass]')).not.toBeNull();
  });

  it('starts Google sign-in from the primary button', async () => {
    renderLogin();
    fireEvent.click(signInButton());
    await waitFor(() => expect(auth.signInWithGoogle).toHaveBeenCalledOnce());
  });

  it('explains a failed sign-in inline', async () => {
    auth.signInWithGoogle.mockRejectedValue(new Error('auth/network-request-failed'));
    renderLogin();
    fireEvent.click(signInButton());
    expect(await screen.findByRole('alert')).toHaveTextContent(/try again/i);
  });

  it('treats a dismissed popup as a non-event', async () => {
    auth.signInWithGoogle.mockRejectedValue(new Error('auth/popup-closed-by-user'));
    renderLogin();
    fireEvent.click(signInButton());
    await waitFor(() => expect(signInButton()).toBeEnabled());
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('waits for the session check before allowing sign-in', () => {
    auth.isLoading = true;
    renderLogin();
    expect(signInButton()).toBeDisabled();
  });

  it('sends a signed-in user home', () => {
    auth.isAuthenticated = true;
    renderLogin();
    expect(screen.getByText('home')).toBeInTheDocument();
  });
});
