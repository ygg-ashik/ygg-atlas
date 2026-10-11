// src/ui/secret-reveal.tsx
import * as React from 'react';
import { Button } from './button';
import { Morph } from './morph';
import { cn } from './utils';

interface SecretRevealBase {
  /** Accessible name of the secret, e.g. "Personal token". */
  label: string;
  className?: string;
}

/** While shown: the caller holds the one-time value only until the reveal is dismissed. */
export interface SecretRevealShownProps extends SecretRevealBase {
  concealed?: false;
  /** The one-time secret. */
  value: string;
  /** Clipboard writer; defaults to the browser clipboard. */
  copy?: (text: string) => Promise<void>;
  onCopied?: () => void;
  /** Usually a `Notice` in the warning tone: "Shown once." */
  children?: React.ReactNode;
}

/** After dismissal: no value at all, only a public, non-secret hint (e.g. the token prefix). */
export interface SecretRevealConcealedProps extends SecretRevealBase {
  concealed: true;
  maskedHint: string;
}

export type SecretRevealProps = SecretRevealShownProps | SecretRevealConcealedProps;

const MASK = '••••••••••••';
const FIELD =
  'flex items-center gap-2.5 rounded-md bg-card-2 py-2.5 pl-3.5 pr-2.5 shadow-[inset_0_0_0_1px_hsl(var(--border))]';
const CODE = 'flex-1 break-all font-mono text-[13px] text-ink';

function browserCopy(text: string): Promise<void> {
  return navigator.clipboard.writeText(text);
}

function Shown({
  value,
  label,
  copy = browserCopy,
  onCopied,
  children,
  className,
}: SecretRevealShownProps) {
  const [copied, setCopied] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  const onCopy = async () => {
    if (copied) return;
    try {
      await copy(value);
      setFailed(false);
      setCopied(true);
      onCopied?.();
    } catch {
      setFailed(true);
    }
  };
  return (
    <div className={cn('grid gap-3.5', className)}>
      <div role="group" aria-label={label} className={FIELD}>
        <code className={CODE}>{value}</code>
        <Button variant="pill" size="sm" onClick={onCopy} aria-label={copied ? 'Copied' : 'Copy'}>
          <Morph done={copied} from="Copy" to="✓ Copied" />
        </Button>
      </div>
      <span role="status" className="sr-only">
        {copied ? 'Copied to clipboard' : ''}
      </span>
      {failed && (
        <p role="alert" className="text-[12.5px] text-negative">
          Couldn&apos;t copy. Select the text and copy it yourself.
        </p>
      )}
      {children}
    </div>
  );
}

/** One-time secret (DESIGN.md › secret-reveal): mono on a recessed field, Copy
 * morphs to "✓ Copied" and copies once. Concealed, it takes no value at all, so
 * callers can drop the secret as soon as the reveal is dismissed. */
export function SecretReveal(props: SecretRevealProps) {
  if (!props.concealed) return <Shown {...props} />;
  return (
    <div className={cn('grid gap-3.5', props.className)}>
      <div role="group" aria-label={props.label} className={FIELD}>
        <code data-concealed="true" className={CODE}>
          {`${props.maskedHint}${MASK}`}
        </code>
      </div>
    </div>
  );
}
