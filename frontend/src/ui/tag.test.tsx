// src/ui/tag.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Tag } from './tag';

describe('Tag', () => {
  it('is a neutral caption chip', () => {
    render(<Tag>service</Tag>);
    expect(screen.getByText('service')).toHaveClass('bg-card-2', 'text-caption', 'rounded-full');
  });

  it('supports a mono variant and a decorative freshness dot', () => {
    render(
      <Tag mono dot>
        group:marketing
      </Tag>,
    );
    const tag = screen.getByText('group:marketing');
    expect(tag).toHaveClass('font-mono');
    expect(tag.querySelector('[aria-hidden]')).toHaveClass('bg-positive');
  });
});
