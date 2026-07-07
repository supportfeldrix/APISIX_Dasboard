import { useState, useCallback } from 'react';
import apiClient from '../api/client';

const EVENT_TYPE_DISPLAY = {
  trigger_file_written: { emoji: '📤', label: 'Trigger File Written' },
  trigger_file_failed: { emoji: '❌', label: 'Trigger File Failed' },
  acknowledged: { emoji: '✅', label: 'Acknowledged' },
  grace_period_expired: { emoji: '⏰', label: 'Grace Period Expired' },
  recovery_file_written: { emoji: '🟢', label: 'Recovery File Written' },
  recovery_cancelled_pending: { emoji: '↩️', label: 'Recovery Cancelled Pending' },
};

function formatEventType(eventType) {
  const display = EVENT_TYPE_DISPLAY[eventType];
  if (!display) return eventType || '—';
  return `${display.emoji} ${display.label}`;
}

function getDetails(entry) {
  switch (entry.event_type) {
    case 'trigger_file_written':
    case 'recovery_file_written':
      return entry.file_path || '—';
    case 'trigger_file_failed':
      return entry.error_msg || '—';
    default:
      return '—';
  }
}

function getUser(entry) {
  if (entry.event_type === 'acknowledged') {
    return entry.username || '—';
  }
  return entry.username || '—';
}

export default function EscalationHistory() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [totalCount, setTotalCount] = useState(0);
  const [filters, setFilters] = useState({
    rule_name: '',
    start_date: '',
    end_date: '',
  });

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = {
        limit: 100,
        ...Object.fromEntries(
          Object.entries(filters).filter(([, v]) => v !== '')
        ),
      };
      const response = await apiClient.get('/escalation/history', { params });
      const data = response.data;
      const items = data.items || data.entries || data || [];
      setEntries(items.slice(0, 1000));
      setTotalCount(data.total || items.length);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to fetch escalation history');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  function handleFilterChange(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  function handleSearch(e) {
    e.preventDefault();
    fetchHistory();
  }

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      {/* Header */}
      <div className="px-4 py-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">Escalation History</h2>
        <p className="text-sm text-gray-500 mt-1">Audit trail for ControlM escalation events</p>
      </div>

      {/* Filters */}
      <form onSubmit={handleSearch} className="px-4 py-3 border-b border-gray-100 bg-gray-50">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="esc-rule-name" className="block text-xs font-medium text-gray-600 mb-1">
              Rule Name
            </label>
            <input
              id="esc-rule-name"
              type="text"
              value={filters.rule_name}
              onChange={(e) => handleFilterChange('rule_name', e.target.value)}
              placeholder="Search rule name..."
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none w-48"
            />
          </div>
          <div>
            <label htmlFor="esc-start-date" className="block text-xs font-medium text-gray-600 mb-1">
              Start Date
            </label>
            <input
              id="esc-start-date"
              type="date"
              value={filters.start_date}
              onChange={(e) => handleFilterChange('start_date', e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor="esc-end-date" className="block text-xs font-medium text-gray-600 mb-1">
              End Date
            </label>
            <input
              id="esc-end-date"
              type="date"
              value={filters.end_date}
              onChange={(e) => handleFilterChange('end_date', e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
          >
            <svg className="w-4 h-4 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            Search
          </button>
        </div>
      </form>

      {/* Error Banner */}
      {error && (
        <div className="mx-4 mt-3 bg-red-50 border border-red-200 rounded-lg p-3">
          <div className="flex items-center">
            <svg className="h-4 w-4 text-red-400 mr-2" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
            <p className="text-sm text-red-700">{error}</p>
          </div>
        </div>
      )}

      {/* Total Count */}
      {!loading && entries.length > 0 && (
        <div className="px-4 py-2 text-sm text-gray-600">
          Showing <span className="font-medium">{entries.length}</span> of{' '}
          <span className="font-medium">{totalCount}</span> entries
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center h-48">
          <div className="flex flex-col items-center space-y-4">
            <div className="animate-spin rounded-full h-10 w-10 border-4 border-indigo-600 border-t-transparent"></div>
            <p className="text-gray-600 text-sm">Loading escalation history...</p>
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Timestamp</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Rule</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Event Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Details</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">User</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {entries.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-500">
                    {totalCount === 0
                      ? 'No escalation history found. Click "Search" to load entries.'
                      : 'No entries match the current filters.'}
                  </td>
                </tr>
              ) : (
                entries.map((entry) => (
                  <tr key={entry.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {entry.created_at ? new Date(entry.created_at).toLocaleString() : '—'}
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">
                      {entry.rule_name || '—'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">
                      {formatEventType(entry.event_type)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700 max-w-[250px] truncate" title={getDetails(entry)}>
                      {getDetails(entry)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">
                      {getUser(entry)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
