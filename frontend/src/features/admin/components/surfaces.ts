// Solid surfaces of the admin screens (DESIGN.md: tables, lists and forms sit on
// solid cards, never glass). One definition per shell so every card matches.

/** A solid card with a hairline ring. */
export const CARD = 'rounded-card bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.6)]';

/** An inset grouped list (rows separated by hairlines). */
export const INSET_LIST =
  'overflow-hidden rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.5)]';

/** A raised editor card (grant editor, group form): full hairline plus a soft lift. */
export const RAISED_CARD =
  'rounded-card bg-card shadow-[0_0_0_1px_hsl(var(--border)),0_6px_20px_hsl(var(--ink)/0.06)]';
