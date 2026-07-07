import { useState, useEffect, useCallback } from 'react';
import apiClient from '../api/client';

/**
 * Custom hook that polls the /metrics endpoint at a configurable interval.
 * @param {number} interval - Polling interval in milliseconds (default 30000ms / 30s)
 * @returns {{ metrics: Array|null, loading: boolean, error: string|null, lastUpdated: Date|null }}
 */
export function useMetrics(interval = 30000) {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const fetchMetrics = useCallback(async () => {
    try {
      const response = await apiClient.get('/metrics');
      setMetrics(response.data);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to fetch metrics');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Initial fetch
    fetchMetrics();

    // Set up polling interval
    const intervalId = setInterval(fetchMetrics, interval);

    // Cleanup on unmount
    return () => clearInterval(intervalId);
  }, [fetchMetrics, interval]);

  return { metrics, loading, error, lastUpdated };
}

export default useMetrics;
