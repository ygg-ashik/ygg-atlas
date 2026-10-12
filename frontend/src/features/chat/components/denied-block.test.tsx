import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { RequestAccessProvider, type OpenRequestAccess } from '@/lib/request-access';
import { AnswerBlocks } from './answer-blocks';
import { DeniedBlock } from './denied-block';

const block = {
  kind: 'denied' as const,
  resource: 'demo/checkout/checkout_funnel',
  label: 'Checkout funnel & more',
};

function renderBlock(open: OpenRequestAccess | null = null) {
  render(
    <RequestAccessProvider value={open}>
      <MemoryRouter initialEntries={['/ask/s1']}>
        <Routes>
          <Route path="/ask/:id" element={<DeniedBlock block={block} />} />
          <Route path="/settings/requests/new" element={<p>request page</p>} />
        </Routes>
      </MemoryRouter>
    </RequestAccessProvider>,
  );
}

describe('DeniedBlock', () => {
  it('states the denial in business language with the resource in mono', () => {
    renderBlock();
    expect(screen.getByText("Checkout funnel & more isn't available to your access")).toBeVisible();
    const path = screen.getByText('demo/checkout/checkout_funnel');
    expect(path).toHaveClass('font-mono');
    expect(screen.getByText('scope · from your Google sign-in')).toBeInTheDocument();
  });

  it('links to the prefilled request page with an encoded query', () => {
    renderBlock();
    const link = screen.getByRole('link', { name: 'Request access' });
    expect(link).toHaveAttribute(
      'href',
      '/settings/requests/new?resource=demo%2Fcheckout%2Fcheckout_funnel&label=Checkout+funnel+%26+more',
    );
  });

  it('opens the request dialog in place, prefilled, when the app hosts one', async () => {
    const open = vi.fn();
    renderBlock(open);
    await userEvent.click(screen.getByRole('link', { name: 'Request access' }));
    expect(open).toHaveBeenCalledWith({ resource: block.resource, label: block.label });
    expect(screen.queryByText('request page')).not.toBeInTheDocument();
  });

  it('follows the link to the request page without a dialog host', async () => {
    renderBlock();
    await userEvent.click(screen.getByRole('link', { name: 'Request access' }));
    expect(screen.getByText('request page')).toBeInTheDocument();
  });

  it('AnswerBlocks renders a denied block', () => {
    render(
      <MemoryRouter>
        <AnswerBlocks
          messageId="m1"
          blocks={[block]}
          actions={{ activeMessageId: 'm1', onChoose: vi.fn(), onOpenArtifact: vi.fn() }}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Request access' })).toBeInTheDocument();
  });
});
