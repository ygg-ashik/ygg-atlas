// src/ui/skeleton.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Skeleton, SkeletonRegion, SkeletonRows } from './skeleton';

describe('Skeleton', () => {
  it('is a decorative shimmering placeholder', () => {
    const { container } = render(<Skeleton shape="circle" />);
    const s = container.querySelector('[data-skeleton]');
    expect(s).toHaveAttribute('aria-hidden');
    expect(s).toHaveAttribute('data-skeleton', 'circle');
    expect(s).toHaveClass('animate-shimmer', 'rounded-full');
  });

  it('a region is busy and announces what is loading', () => {
    const { container } = render(
      <SkeletonRegion label="users">
        <SkeletonRows count={3} />
      </SkeletonRegion>,
    );
    expect(container.firstChild).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Loading users');
    expect(container.querySelectorAll('[data-skeleton="circle"]')).toHaveLength(3);
  });
});
