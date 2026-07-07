import { useEffect, useRef, useCallback } from 'react';
import { useAuthStore } from '../store/authStore';

/**
 * Auto-logout after inactivity.
 * @param {number} timeoutMs - Inactivity timeout in milliseconds (default 30 minutes)
 */
export function useSessionTimeout(timeoutMs = 30 * 60 * 1000) {
  const timerRef = useRef(null);
  const { token, clearAuth } = useAuthStore();

  const handleLogout = useCallback(() => {
    if (token) {
      clearAuth();
      window.location.href = '/login?reason=timeout';
    }
  }, [token, clearAuth]);

  const resetTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    if (token) {
      timerRef.current = setTimeout(handleLogout, timeoutMs);
    }
  }, [token, timeoutMs, handleLogout]);

  useEffect(() => {
    if (!token) return;

    // Events that indicate user activity
    const events = ['mousedown', 'keydown', 'scroll', 'touchstart', 'mousemove'];

    events.forEach((event) => {
      window.addEventListener(event, resetTimer, { passive: true });
    });

    // Start the timer
    resetTimer();

    return () => {
      events.forEach((event) => {
        window.removeEventListener(event, resetTimer);
      });
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [token, resetTimer]);
}

export default useSessionTimeout;
