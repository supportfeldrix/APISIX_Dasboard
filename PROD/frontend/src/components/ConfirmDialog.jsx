import { useEffect, useRef, useCallback } from 'react';

/**
 * ConfirmDialog — Accessible modal dialog for destructive/warning confirmations.
 *
 * Props:
 *   open          — boolean controlling visibility
 *   title         — dialog title string
 *   message       — dialog message/body string
 *   confirmLabel  — text for confirm button (default "Delete")
 *   cancelLabel   — text for cancel button (default "Cancel")
 *   onConfirm()   — callback when confirmed
 *   onCancel()    — callback when cancelled
 *   variant       — "danger" | "warning" (default "danger") — controls confirm button color
 *   disabled      — boolean (default false) — when true, confirm button shows spinner and is non-clickable
 */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Delete',
  cancelLabel = 'Cancel',
  onConfirm,
  onCancel,
  variant = 'danger',
  disabled = false,
}) {
  const cancelButtonRef = useRef(null);
  const dialogRef = useRef(null);

  // Auto-focus the cancel button when dialog opens (safer default)
  useEffect(() => {
    if (open && cancelButtonRef.current) {
      cancelButtonRef.current.focus();
    }
  }, [open]);

  // ESC key closes the dialog
  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onCancel?.();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onCancel]);

  // Focus trap: keep Tab within the dialog
  const handleKeyDown = useCallback(
    (e) => {
      if (e.key !== 'Tab' || !dialogRef.current) return;

      const focusableElements = dialogRef.current.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );

      if (focusableElements.length === 0) return;

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      if (e.shiftKey) {
        // Shift+Tab: if on first element, wrap to last
        if (document.activeElement === firstElement) {
          e.preventDefault();
          lastElement.focus();
        }
      } else {
        // Tab: if on last element, wrap to first
        if (document.activeElement === lastElement) {
          e.preventDefault();
          firstElement.focus();
        }
      }
    },
    []
  );

  if (!open) return null;

  const confirmButtonClasses =
    variant === 'warning'
      ? 'bg-amber-500 hover:bg-amber-600 focus:ring-amber-500 text-white'
      : 'bg-red-600 hover:bg-red-700 focus:ring-red-500 text-white';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onKeyDown={handleKeyDown}
    >
      {/* Dark overlay backdrop */}
      <div
        className="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
        aria-hidden="true"
        onClick={onCancel}
      />

      {/* Dialog container */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        className="relative z-10 w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
      >
        {/* Title */}
        <h2
          id="confirm-dialog-title"
          className="text-lg font-semibold text-gray-900"
        >
          {title}
        </h2>

        {/* Message */}
        <p className="mt-2 text-sm text-gray-600">{message}</p>

        {/* Action buttons */}
        <div className="mt-6 flex justify-end gap-3">
          <button
            ref={cancelButtonRef}
            type="button"
            onClick={onCancel}
            className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={disabled ? undefined : onConfirm}
            disabled={disabled}
            aria-disabled={disabled}
            className={`rounded-md px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-offset-2 ${confirmButtonClasses}${disabled ? ' opacity-50 cursor-not-allowed' : ''}`}
          >
            {disabled && (
              <svg
                className="inline-block mr-2 h-4 w-4 animate-spin text-current"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            )}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
