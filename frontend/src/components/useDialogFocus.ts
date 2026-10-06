import { RefObject, useEffect, useRef } from 'react';

export default function useDialogFocus(dialog: RefObject<HTMLDivElement>, onClose: () => void, busy: boolean, initialSelector: string, backgroundSelector = '.app') {
  const closeAction = useRef(onClose);
  const isBusy = useRef(busy);
  closeAction.current = onClose;
  isBusy.current = busy;
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    const app = document.querySelector(backgroundSelector);
    const previousInert = app?.hasAttribute('inert');
    app?.setAttribute('inert', '');
    document.body.style.overflow = 'hidden';
    dialog.current?.querySelector<HTMLElement>(initialSelector)?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); if (!isBusy.current) closeAction.current(); }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled)') ?? []);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (!first) { event.preventDefault(); dialog.current?.focus(); return; }
      if (!focusable.includes(document.activeElement as HTMLElement)) { event.preventDefault(); (event.shiftKey ? last : first).focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', handleKey, true);
    return () => {
      document.removeEventListener('keydown', handleKey, true);
      document.body.style.overflow = previousOverflow;
      if (!previousInert) app?.removeAttribute('inert');
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [dialog, initialSelector, backgroundSelector]);
}
