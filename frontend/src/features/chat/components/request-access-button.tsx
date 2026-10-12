import { Link } from 'react-router-dom';
import { useRequestAccess } from '@/lib/request-access';
import { type RequestPrefill } from '@/lib/routes';
import { Button, type ButtonProps } from '@/ui';

interface RequestAccessButtonProps {
  /** The prefilled request page (a modified click, or no dialog host). */
  to: string;
  /** The same prefill, for the dialog. */
  prefill: RequestPrefill;
  size?: ButtonProps['size'];
}

/** "Request access" from the chat: opens the request dialog over the chat when
 * App.tsx hosts it; otherwise (or on a modified click) the prefilled request page. */
export function RequestAccessButton({ to, prefill, size }: RequestAccessButtonProps) {
  const open = useRequestAccess();
  return (
    <Button asChild size={size}>
      <Link
        to={to}
        onClick={(e) => {
          if (!open || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
          e.preventDefault();
          open(prefill);
        }}
      >
        Request access
      </Link>
    </Button>
  );
}
