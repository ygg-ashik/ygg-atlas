import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AnswerBlocks } from './answer-blocks';
import { DeniedBlock, requestAccessHref } from './denied-block';

const block = {
  kind: 'denied' as const,
  resource: 'demo/checkout/checkout_funnel',
  label: 'Checkout funnel & more',
};

function renderBlock() {
  render(
    <MemoryRouter>
      <DeniedBlock block={block} />
    </MemoryRouter>,
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

  it('links to a prefilled request with an encoded query', () => {
    renderBlock();
    const link = screen.getByRole('link', { name: 'Request access' });
    expect(link).toHaveAttribute(
      'href',
      '/account/requests/new?resource=demo%2Fcheckout%2Fcheckout_funnel&label=Checkout+funnel+%26+more',
    );
  });

  it('the href round-trips through URLSearchParams', () => {
    const href = requestAccessHref(block.resource, block.label);
    const params = new URLSearchParams(href.split('?')[1]);
    expect(params.get('resource')).toBe(block.resource);
    expect(params.get('label')).toBe(block.label);
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
