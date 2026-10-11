import { StatusPill } from '@/ui';

/** allow (positive dot) or deny (negative diamond): never colour alone. */
export function EffectPill({ effect }: { effect: string }) {
  return effect === 'allow' ? (
    <StatusPill tone="positive">allow</StatusPill>
  ) : (
    <StatusPill tone="negative" diamond>
      deny
    </StatusPill>
  );
}
