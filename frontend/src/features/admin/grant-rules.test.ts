import { describe, expect, it } from 'vitest';
import {
  expiryToIso,
  isResourcePath,
  matches,
  patternError,
  plusDays,
  todayUtc,
  validateGrantDraft,
  type GrantDraft,
} from './grant-rules';

// Same table as backend tests/access/test_patterns.py: the editor and the
// evaluator must agree on every pattern.
describe('matches (mirrors app/access/patterns.py)', () => {
  it.each([
    ['*', 'demo/order/revenue', true],
    ['*', 'demo/order', true],
    ['demo/*', 'demo/order/revenue', true],
    ['demo/*', 'demo/order', true],
    ['demo/*', 'demo', true],
    ['demo/order/*', 'demo/order/revenue', true],
    ['demo/order/*', 'demo/order', true],
    ['demo/order/*', 'demo/checkout/checkout_funnel', false],
    ['demo/order/revenue', 'demo/order/revenue', true],
    ['demo/order/revenue', 'demo/order/aov', false],
    ['demo/*/revenue', 'demo/order/revenue', true],
    ['demo/*/revenue', 'demo/order/aov', false],
    ['deepsales/*', 'demo/order/revenue', false],
    ['demo/order', 'demo/order', true],
    ['demo/order', 'demo/order/revenue', false],
    ['*', '', false],
  ])('%s covers %s → %s', (pattern, path, expected) => {
    expect(matches(pattern, path)).toBe(expected);
  });
});

describe('patternError', () => {
  it.each(['*', 'deepsales/*', 'demo/order/revenue', 'demo/*/revenue'])('%s is valid', (p) => {
    expect(patternError(p)).toBeNull();
  });

  it.each([
    '',
    'demo//x',
    'Demo/*',
    'demo/order/revenue/x',
    'demo/*x',
    'demo/a b',
    '../x',
    'demo',
    'demo/order',
  ])('%s is invalid', (p) => {
    expect(patternError(p)).not.toBeNull();
  });

  it('suggests the trailing-star form for an entity', () => {
    expect(patternError('demo/order')).toContain('demo/order/*');
  });
});

describe('isResourcePath', () => {
  it.each([
    ['demo/order/revenue', true],
    ['demo/order', true],
    ['demo', false],
    ['', false],
    ['demo/order/revenue/extra', false],
    ['demo//x', false],
    ['Demo/order/revenue', false],
    ['demo/ord er/revenue', false],
    ['demo/*/revenue', false],
    ['demo/order/', false],
  ])('%s → %s', (path, expected) => {
    expect(isResourcePath(path)).toBe(expected);
  });
});

describe('grant draft', () => {
  const TODAY = '2026-10-09';
  const base: GrantDraft = {
    subjectType: 'group',
    targetKind: 'resource',
    target: 'demo/order/*',
    effect: 'allow',
    expiry: '',
    reason: '',
    denyConfirmed: false,
  };

  it('accepts a plain group allow', () => {
    expect(validateGrantDraft(base, TODAY)).toEqual({});
  });

  it('needs a target, and a valid pattern', () => {
    expect(validateGrantDraft({ ...base, target: '' }, TODAY).target).toBeTruthy();
    expect(validateGrantDraft({ ...base, target: 'demo/order' }, TODAY).target).toContain('/*');
  });

  it('a deny needs confirmation', () => {
    const deny = { ...base, effect: 'deny' as const };
    expect(validateGrantDraft(deny, TODAY).confirm).toBeTruthy();
    expect(validateGrantDraft({ ...deny, denyConfirmed: true }, TODAY)).toEqual({});
  });

  it('a direct user grant needs a reason (the backend sentence)', () => {
    const user = { ...base, subjectType: 'user' as const };
    expect(validateGrantDraft(user, TODAY).reason).toBe('Direct user grants need a reason.');
    expect(validateGrantDraft({ ...user, reason: '  ' }, TODAY).reason).toBeTruthy();
    expect(validateGrantDraft({ ...user, reason: 'Q4 planning' }, TODAY)).toEqual({});
  });

  it('the expiry is an ISO date in the future', () => {
    expect(validateGrantDraft({ ...base, expiry: '2026-13-01' }, TODAY).expiry).toContain(
      'YYYY-MM-DD',
    );
    expect(validateGrantDraft({ ...base, expiry: TODAY }, TODAY).expiry).toBe(
      'The expiry must be in the future.',
    );
    expect(validateGrantDraft({ ...base, expiry: '2026-10-10' }, TODAY)).toEqual({});
  });

  it('dates are UTC', () => {
    expect(todayUtc(new Date('2026-10-09T23:30:00-05:00'))).toBe('2026-10-10');
    expect(plusDays('2026-10-09', 90)).toBe('2027-01-07');
    expect(expiryToIso('2026-12-31')).toBe('2026-12-31T00:00:00Z');
    expect(expiryToIso('')).toBeNull();
  });
});
