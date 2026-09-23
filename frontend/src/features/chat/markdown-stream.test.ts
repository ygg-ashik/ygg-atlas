import { describe, expect, it } from 'vitest';
import { stabilizeStreamingMarkdown } from './markdown-stream';

describe('stabilizeStreamingMarkdown', () => {
  it('leaves complete markdown untouched', () => {
    const text = 'Revenue was **AED 1.2M** (`revenue_total`).';
    expect(stabilizeStreamingMarkdown(text)).toBe(text);
  });

  it('trims a trailing unclosed bold marker', () => {
    expect(stabilizeStreamingMarkdown('Revenue was **AED 1.2')).toBe('Revenue was ');
  });

  it('trims a trailing unclosed code span', () => {
    expect(stabilizeStreamingMarkdown('See `revenue_tot')).toBe('See ');
  });

  it('ignores ** inside complete code spans', () => {
    const text = 'Use `a ** b` for exponent.';
    expect(stabilizeStreamingMarkdown(text)).toBe(text);
  });

  it('trims a trailing incomplete link', () => {
    expect(stabilizeStreamingMarkdown('See [the dashboard](https://exa')).toBe('See ');
  });

  it('trims a table row missing its closing pipe', () => {
    const text = '| Metric | Value |\n| --- | --- |\n| Revenue | 1.2';
    expect(stabilizeStreamingMarkdown(text)).toBe('| Metric | Value |\n| --- | --- |\n');
  });
});
