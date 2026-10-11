// src/ui/diff-block.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DiffBlock } from './diff-block';

describe('DiffBlock', () => {
  it('renders add, remove and context lines with visible marks', () => {
    render(
      <DiffBlock
        lines={[
          { kind: 'context', text: 'request r-1' },
          { kind: 'remove', text: 'role viewer' },
          { kind: 'add', text: 'role analyst' },
        ]}
      />,
    );
    const removed = screen.getByText('role viewer');
    expect(removed).toHaveAttribute('data-kind', 'remove');
    expect(removed).toHaveClass('line-through', 'text-negative');
    expect(removed).toHaveTextContent('− removed: role viewer');
    expect(screen.getByText('role analyst')).toHaveTextContent('+ added: role analyst');
    expect(screen.getByText('request r-1')).toHaveClass('text-muted-foreground');
  });
});
