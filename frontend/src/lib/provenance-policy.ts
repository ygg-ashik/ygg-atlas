// src/lib/provenance-policy.ts
// Plain-language labels for the policy that shaped a number (DESIGN.md › Policy
// chips): the row scope (dimension names only) and any breakdown-label masking.
// A view of backend provenance only; the UI never decides access.
import type { Provenance, ProvenanceMasking, ProvenanceScope } from '@/api/chat';

const CLASS_NOUN: Readonly<Record<string, string>> = {
  business_name: 'account names',
  person_name: 'people names',
};

const MODE_PAST: Readonly<Record<string, string>> = {
  pseudonymise: 'pseudonymised',
  suppress: 'suppressed',
  bucket: 'bucketed',
};

export function scopeLabel(scope: ProvenanceScope | null | undefined): string | null {
  if (!scope?.restricted) return null;
  return scope.dimensions.length > 0
    ? `rows · scoped to ${scope.dimensions.join(', ')}`
    : 'rows · scoped';
}

export function maskingLabel(masking: ProvenanceMasking | null | undefined): string | null {
  if (!masking) return null;
  const noun = CLASS_NOUN[masking.label_class] ?? 'names';
  return `${noun} · ${MODE_PAST[masking.mode] ?? masking.mode}`;
}

/** Scope and masking labels across provenance records, deduplicated, in order. */
export function policyLabels(provenance: readonly Provenance[]): string[] {
  const labels = provenance.flatMap((p) => [scopeLabel(p.scope), maskingLabel(p.masking)]);
  return Array.from(new Set(labels.filter((l): l is string => l !== null)));
}

/** Masking facts a breakdown carries (backend D3.8); both absent when unmasked. */
export interface BreakdownMasking {
  suppressed_rows?: number | null;
  others_covers?: string | null;
}

/** What masking changed in a breakdown, stated as fact, or null when unmasked. */
export function maskingNote({
  suppressed_rows: hidden,
  others_covers: covers,
}: BreakdownMasking): string | null {
  if (hidden !== null && hidden !== undefined) {
    return `${hidden} ${hidden === 1 ? 'row' : 'rows'} hidden by name masking`;
  }
  return covers ? `Others = ${covers}` : null;
}
