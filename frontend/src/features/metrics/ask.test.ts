// src/features/metrics/ask.test.ts
import { describe, expect, it } from 'vitest';
import { askHref } from './ask';

describe('askHref', () => {
  it('asks range metrics for the last 30 days', () => {
    expect(askHref({ name: 'Corporate revenue', time_scope: 'range' })).toBe(
      '/ask?q=What%20was%20Corporate%20revenue%20over%20the%20last%2030%20days%3F',
    );
  });
  it('asks snapshot metrics as of now', () => {
    expect(askHref({ name: 'Open tasks', time_scope: 'snapshot' })).toBe(
      '/ask?q=What%20is%20Open%20tasks%20right%20now%3F',
    );
  });
  it('asks funnels for drop-off', () => {
    expect(askHref({ name: 'Checkout funnel' })).toBe(
      '/ask?q=Where%20do%20users%20drop%20off%20in%20Checkout%20funnel%20over%20the%20last%2030%20days%3F',
    );
  });
});
