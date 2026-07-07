import { useState, useEffect, useCallback } from 'react';
import apiClient from '../api/client';
import { getRules, deleteRule, toggleRule, getLogs, sendTestEmail } from '../api/notifications';
import AlertRuleForm from '../components/AlertRuleForm';
import ConfirmDialog from '../components/ConfirmDialog';
import EscalationHistory from '../components/EscalationHistory';
import { useAuthStore } from '../store/authStore';
import EscalationBadge from '../components/EscalationBadge';

const CONDITION_LABELS = {
  JWT_FAILURE: 'JWT Failure',
  UPSTREAM_ERROR: 'Upstream Error',
  CLIENT_ERROR: 'Client Error (4xx)',
  HIGH_ERROR_RATE: 'High Error Rate',
  HEALTH_CHECK_FAILURE: 'Health Check Failure',
  POD_HEALTH: 'Pod Health',
};

const CONDITION_TYPES = [
  { value: 'JWT_FAILURE', label: 'JWT Failure' },
  { value: 'UPSTREAM_ERROR', label: 'Upstream Error' },
  { value: 'CLIENT_ERROR', label: 'Client Error (4xx)' },
  { value: 'HIGH_ERROR_RATE', label: 'High Error Rate' },
  { value: 'HEALTH_CHECK_FAILURE', label: 'Health Check Failure' },
  { value: 'POD_HEALTH', label: 'Pod Health' },
];

const DELIVERY_STATUSES = [
  { value: 'SENT', label: 'Sent' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'RETRYING', label: 'Retrying' },
];

const STATUS_COLORS = {
  SENT: 'bg-green-100 text-green-800',
  FAILED: 'bg-red-100 text-red-800',
  RETRYING: 'bg-yellow-100 text-yellow-800',
};

function formatCooldown(seconds) {
  if (seconds >= 3600) {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  }
  return `${Math.floor(seconds / 60)}m`;
}

export default function Notifications() {
  const role = useAuthStore((s) => s.role);
  const canViewEscalation = role === 'admin' || role === 'viewer';
  const [activeTab, setActiveTab] = useState('rules');

  // ─── Alert Rules State ──────────────────────────────────────────────────
  const [rules, setRules] = useState([]);
  const [rulesLoading, setRulesLoading] = useState(true);
  const [rulesError, setRulesError] = useState('');

  // ─── Form Modal State ───────────────────────────────────────────────────
  const [formOpen, setFormOpen] = useState(false);
  const [editingRule, setEditingRule] = useState(null);
  const [routes, setRoutes] = useState([]);

  // ─── Delete Confirmation State ──────────────────────────────────────────
  const [deleteTarget, setDeleteTarget] = useState(null);

  // ─── Test Email State ───────────────────────────────────────────────────
  const [testEmailOpen, setTestEmailOpen] = useState(false);
  const [testEmailAddress, setTestEmailAddress] = useState('');
  const [testEmailSending, setTestEmailSending] = useState(false);
  const [testEmailResult, setTestEmailResult] = useState(null);

  // ─── Escalation Status State ──────────────────────────────────────────────
  const [escalationStatuses, setEscalationStatuses] = useState({});

  // ─── Notification History State ─────────────────────────────────────────
  const [logs, setLogs] = useState([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState('');
  const [logsPagination, setLogsPagination] = useState({ total: 0, page: 1, page_size: 25 });
  const [logsFilters, setLogsFilters] = useState({
    route_id: '',
    condition_type: '',
    delivery_status: '',
    date_from: '',
    date_to: '',
  });

  // ─── Fetch Alert Rules ──────────────────────────────────────────────────
  const fetchRules = useCallback(async () => {
    setRulesLoading(true);
    setRulesError('');
    try {
      const response = await getRules({ page: 1, page_size: 100 });
      const data = response.data;
      setRules(data.items || data.rules || data || []);
    } catch (err) {
      setRulesError(err.response?.data?.detail || err.message || 'Failed to fetch alert rules');
    } finally {
      setRulesLoading(false);
    }
  }, []);

  // ─── Fetch Routes (for form dropdown) ──────────────────────────────────
  const fetchRoutes = useCallback(async () => {
    try {
      const response = await apiClient.get('/apisix/routes');
      const list = response.data?.list || response.data?.rows || response.data || [];
      const normalized = list.map((entry) => entry.value || entry);
      setRoutes(normalized);
    } catch (err) {
      console.error('Failed to fetch routes:', err);
    }
  }, []);

  // ─── Fetch Notification Logs ────────────────────────────────────────────
  const fetchLogs = useCallback(async (page = 1) => {
    setLogsLoading(true);
    setLogsError('');
    try {
      const params = {
        page,
        page_size: 25,
        ...Object.fromEntries(
          Object.entries(logsFilters).filter(([, v]) => v !== '')
        ),
      };
      const response = await getLogs(params);
      const data = response.data;
      setLogs(data.items || data.logs || []);
      setLogsPagination({
        total: data.total || 0,
        page: data.page || page,
        page_size: data.page_size || 25,
      });
    } catch (err) {
      setLogsError(err.response?.data?.detail || err.message || 'Failed to fetch notification logs');
    } finally {
      setLogsLoading(false);
    }
  }, [logsFilters]);

  // ─── Fetch Escalation Statuses ────────────────────────────────────────────
  const fetchEscalationStatuses = useCallback(async () => {
    try {
      const response = await apiClient.get('/escalation/status');
      setEscalationStatuses(response.data?.statuses || {});
    } catch (err) {
      // Silently fail — escalation feature may not be enabled
      console.error('Failed to fetch escalation statuses:', err);
    }
  }, []);

  // ─── Effects ────────────────────────────────────────────────────────────
  useEffect(() => {
    fetchRules();
    fetchRoutes();
    fetchEscalationStatuses();

    // Auto-refresh escalation statuses every 30 seconds
    const interval = setInterval(fetchEscalationStatuses, 30000);
    return () => clearInterval(interval);
  }, [fetchRules, fetchRoutes, fetchEscalationStatuses]);

  useEffect(() => {
    if (activeTab === 'history') {
      fetchLogs(1);
    }
  }, [activeTab, fetchLogs]);

  // ─── Rule Actions ───────────────────────────────────────────────────────
  function handleCreateRule() {
    setEditingRule(null);
    setFormOpen(true);
  }

  function handleEditRule(rule) {
    setEditingRule(rule);
    setFormOpen(true);
  }

  function handleFormClose() {
    setFormOpen(false);
    setEditingRule(null);
  }

  async function handleFormSubmit(formData) {
    try {
      if (editingRule) {
        await apiClient.put(`/notifications/rules/${editingRule.id}`, formData);
      } else {
        await apiClient.post('/notifications/rules', formData);
      }
      setFormOpen(false);
      setEditingRule(null);
      setRulesError('');
      await fetchRules();
    } catch (err) {
      const message = err.response?.data?.detail || err.message || 'Failed to save alert rule';
      setRulesError(message);
      throw err; // Re-throw so the form knows submission failed and preserves data
    }
  }

  async function handleToggleRule(rule) {
    try {
      await toggleRule(rule.id);
      setRulesError('');
      await fetchRules();
    } catch (err) {
      setRulesError(err.response?.data?.detail || err.message || 'Failed to toggle rule');
    }
  }

  function handleDeleteRule(rule) {
    setDeleteTarget(rule);
  }

  async function handleDeleteConfirm() {
    if (!deleteTarget) return;
    try {
      await deleteRule(deleteTarget.id);
      setDeleteTarget(null);
      setRulesError('');
      await fetchRules();
    } catch (err) {
      setRulesError(err.response?.data?.detail || err.message || 'Failed to delete rule');
      setDeleteTarget(null);
    }
  }

  function handleDeleteCancel() {
    setDeleteTarget(null);
  }

  async function handleTestFire(rule) {
    try {
      setRulesError('');
      const response = await apiClient.post(`/notifications/rules/${rule.id}/test-fire`);
      const data = response.data;
      alert(`✅ Test alert sent!\n\nSubject: ${data.subject}\nRecipients: ${data.recipients.join(', ')}`);
    } catch (err) {
      const message = err.response?.data?.detail || err.message || 'Failed to send test alert';
      setRulesError(`Test fire failed: ${message}`);
    }
  }

  async function handleSendTestEmail() {
    if (!testEmailAddress.trim()) return;
    setTestEmailSending(true);
    setTestEmailResult(null);
    try {
      const response = await sendTestEmail(testEmailAddress.trim());
      setTestEmailResult({ success: true, message: response.data?.message || 'Test email sent successfully!' });
    } catch (err) {
      setTestEmailResult({ success: false, message: err.response?.data?.detail || err.message || 'Failed to send test email' });
    } finally {
      setTestEmailSending(false);
    }
  }

  // ─── History Pagination ─────────────────────────────────────────────────
  const totalPages = Math.ceil(logsPagination.total / logsPagination.page_size);

  function handlePageChange(newPage) {
    if (newPage < 1 || newPage > totalPages) return;
    fetchLogs(newPage);
  }

  function handleFilterChange(key, value) {
    setLogsFilters((prev) => ({ ...prev, [key]: value }));
  }

  // ─── Helper: find route name by ID ─────────────────────────────────────
  function getRouteName(routeId) {
    const route = routes.find((r) => r.id === routeId);
    return route?.name || route?.uri || routeId || '—';
  }

  // ─── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Notifications</h1>
        {activeTab === 'rules' && (
          <div className="flex items-center gap-3">
            <button
              onClick={() => { setTestEmailOpen(true); setTestEmailResult(null); }}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
            >
              <svg className="w-4 h-4 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              Test Email
            </button>
            <button
              onClick={handleCreateRule}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
            >
              <svg
                className="w-4 h-4 mr-1.5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              Create Rule
            </button>
          </div>
        )}
      </div>

      {/* Error Banner */}
      {(rulesError || logsError) && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center">
            <svg className="h-5 w-5 text-red-400 mr-2" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
            <p className="text-sm text-red-700">
              <span className="font-medium">Error:</span> {rulesError || logsError}
            </p>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8" aria-label="Tabs">
          <button
            onClick={() => setActiveTab('rules')}
            className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium transition-colors ${
              activeTab === 'rules'
                ? 'border-indigo-500 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Alert Rules
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium transition-colors ${
              activeTab === 'history'
                ? 'border-indigo-500 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Notification History
          </button>
          {canViewEscalation && (
            <button
              onClick={() => setActiveTab('escalation')}
              className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium transition-colors ${
                activeTab === 'escalation'
                  ? 'border-indigo-500 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              Escalation History
            </button>
          )}
        </nav>
      </div>

      {/* ─── Alert Rules Tab ─────────────────────────────────────────────── */}
      {activeTab === 'rules' && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          {rulesLoading ? (
            <div className="flex items-center justify-center h-64">
              <div className="flex flex-col items-center space-y-4">
                <div className="animate-spin rounded-full h-12 w-12 border-4 border-indigo-600 border-t-transparent"></div>
                <p className="text-gray-600 text-sm">Loading alert rules...</p>
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Route</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Condition</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Threshold</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Recipients</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cooldown</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {rules.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-500">
                        No alert rules configured. Click "Create Rule" to get started.
                      </td>
                    </tr>
                  ) : (
                    rules.map((rule) => (
                      <tr key={rule.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm font-medium text-gray-900">
                          <span className="inline-flex items-center gap-2">
                            {rule.name}
                            {rule.notify_controlm && (
                              <EscalationBadge
                                status={escalationStatuses[rule.id]}
                                ruleId={rule.id}
                                critical={rule.critical}
                                onAcknowledge={fetchEscalationStatuses}
                              />
                            )}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700">
                          {rule.route_name || getRouteName(rule.route_id)}
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                            {CONDITION_LABELS[rule.condition_type] || rule.condition_type}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700">
                          {rule.threshold}{rule.condition_type === 'HIGH_ERROR_RATE' ? '%' : ''}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700">
                          <span title={Array.isArray(rule.recipients) ? rule.recipients.join(', ') : rule.recipients}>
                            {Array.isArray(rule.recipients) ? rule.recipients.length : '—'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700">
                          {formatCooldown(rule.cooldown_seconds)}
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <button
                            type="button"
                            role="switch"
                            aria-checked={rule.enabled}
                            onClick={() => handleToggleRule(rule)}
                            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 ${
                              rule.enabled ? 'bg-indigo-600' : 'bg-gray-200'
                            }`}
                          >
                            <span
                              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                rule.enabled ? 'translate-x-6' : 'translate-x-1'
                              }`}
                            />
                          </button>
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => handleTestFire(rule)}
                              className="text-amber-600 hover:text-amber-900 focus:outline-none"
                              title="Test fire alert"
                            >
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M15.362 5.214A8.252 8.252 0 0112 21 8.25 8.25 0 016.038 7.048 8.287 8.287 0 009 9.6a8.983 8.983 0 013.361-6.867 8.21 8.21 0 003 2.48z" />
                                <path strokeLinecap="round" strokeLinejoin="round" d="M12 18a3.75 3.75 0 00.495-7.467 5.99 5.99 0 00-1.925 3.546 5.974 5.974 0 01-2.133-1A3.75 3.75 0 0012 18z" />
                              </svg>
                            </button>
                            <button
                              onClick={() => handleEditRule(rule)}
                              className="text-indigo-600 hover:text-indigo-900 focus:outline-none"
                              title="Edit rule"
                            >
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                              </svg>
                            </button>
                            <button
                              onClick={() => handleDeleteRule(rule)}
                              className="text-red-600 hover:text-red-900 focus:outline-none"
                              title="Delete rule"
                            >
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ─── Notification History Tab ────────────────────────────────────── */}
      {activeTab === 'history' && (
        <div className="space-y-4">
          {/* Filters */}
          <div className="flex flex-wrap gap-3">
            <select
              value={logsFilters.route_id}
              onChange={(e) => handleFilterChange('route_id', e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            >
              <option value="">All Routes</option>
              {routes.map((route) => (
                <option key={route.id} value={route.id}>
                  {route.name || route.uri || route.id}
                </option>
              ))}
            </select>

            <select
              value={logsFilters.condition_type}
              onChange={(e) => handleFilterChange('condition_type', e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            >
              <option value="">All Conditions</option>
              {CONDITION_TYPES.map((ct) => (
                <option key={ct.value} value={ct.value}>
                  {ct.label}
                </option>
              ))}
            </select>

            <select
              value={logsFilters.delivery_status}
              onChange={(e) => handleFilterChange('delivery_status', e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            >
              <option value="">All Statuses</option>
              {DELIVERY_STATUSES.map((ds) => (
                <option key={ds.value} value={ds.value}>
                  {ds.label}
                </option>
              ))}
            </select>

            <input
              type="date"
              value={logsFilters.date_from}
              onChange={(e) => handleFilterChange('date_from', e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              placeholder="From date"
              title="From date"
            />

            <input
              type="date"
              value={logsFilters.date_to}
              onChange={(e) => handleFilterChange('date_to', e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              placeholder="To date"
              title="To date"
            />
          </div>

          {/* Logs Table */}
          <div className="bg-white rounded-lg shadow overflow-hidden">
            {logsLoading ? (
              <div className="flex items-center justify-center h-64">
                <div className="flex flex-col items-center space-y-4">
                  <div className="animate-spin rounded-full h-12 w-12 border-4 border-indigo-600 border-t-transparent"></div>
                  <p className="text-gray-600 text-sm">Loading notification history...</p>
                </div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Timestamp</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Route</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Condition</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Recipients</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Subject</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Error</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {logs.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                          No notification logs found
                        </td>
                      </tr>
                    ) : (
                      logs.map((log) => (
                        <tr key={log.id} className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                            {new Date(log.timestamp).toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-700">
                            {log.route_name || getRouteName(log.route_id)}
                          </td>
                          <td className="px-4 py-3 text-sm">
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                              {CONDITION_LABELS[log.condition_type] || log.condition_type}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-700">
                            <span title={Array.isArray(log.recipients) ? log.recipients.join(', ') : log.recipients}>
                              {Array.isArray(log.recipients) ? log.recipients.join(', ') : log.recipients}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-700 max-w-[200px] truncate" title={log.subject}>
                            {log.subject || '—'}
                          </td>
                          <td className="px-4 py-3 text-sm">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                              STATUS_COLORS[log.delivery_status] || 'bg-gray-100 text-gray-800'
                            }`}>
                              {log.delivery_status}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-xs text-gray-500 max-w-[150px] truncate" title={log.error_message}>
                            {log.error_message || '—'}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {!logsLoading && logsPagination.total > 0 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 bg-gray-50">
                <p className="text-sm text-gray-700">
                  Showing{' '}
                  <span className="font-medium">
                    {(logsPagination.page - 1) * logsPagination.page_size + 1}
                  </span>
                  {' '}to{' '}
                  <span className="font-medium">
                    {Math.min(logsPagination.page * logsPagination.page_size, logsPagination.total)}
                  </span>
                  {' '}of{' '}
                  <span className="font-medium">{logsPagination.total}</span> results
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handlePageChange(logsPagination.page - 1)}
                    disabled={logsPagination.page <= 1}
                    className="px-3 py-1 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    Previous
                  </button>
                  <span className="text-sm text-gray-700">
                    Page {logsPagination.page} of {totalPages}
                  </span>
                  <button
                    onClick={() => handlePageChange(logsPagination.page + 1)}
                    disabled={logsPagination.page >= totalPages}
                    className="px-3 py-1 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ─── Escalation History Tab ────────────────────────────────────── */}
      {activeTab === 'escalation' && canViewEscalation && (
        <EscalationHistory />
      )}

      {/* ─── Alert Rule Form Modal ───────────────────────────────────────── */}
      <AlertRuleForm
        isOpen={formOpen}
        onClose={handleFormClose}
        onSubmit={handleFormSubmit}
        initialData={editingRule}
        routes={routes}
      />

      {/* ─── Delete Confirmation Dialog ──────────────────────────────────── */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete Alert Rule"
        message={`Are you sure you want to delete the alert rule "${deleteTarget?.name || ''}"? This action cannot be undone.`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
        variant="danger"
      />

      {/* Test Email Modal */}
      {testEmailOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black bg-opacity-50" onClick={() => setTestEmailOpen(false)} />
          <div className="relative z-10 bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <div className="flex items-center mb-4">
              <div className="flex-shrink-0 w-10 h-10 rounded-full bg-indigo-100 flex items-center justify-center">
                <svg className="h-5 w-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
              </div>
              <h3 className="ml-3 text-lg font-semibold text-gray-900">Send Test Email</h3>
            </div>
            <p className="text-sm text-gray-600 mb-4">Send a test email to verify your SMTP configuration is working.</p>
            <div className="mb-4">
              <label htmlFor="test-email-address" className="block text-sm font-medium text-gray-700 mb-1">
                Recipient Email
              </label>
              <input
                id="test-email-address"
                type="email"
                value={testEmailAddress}
                onChange={(e) => setTestEmailAddress(e.target.value)}
                placeholder="your.email@fnb.co.za"
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            {testEmailResult && (
              <div className={`mb-4 p-3 rounded-md text-sm ${testEmailResult.success ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
                {testEmailResult.message}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setTestEmailOpen(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400"
              >
                Close
              </button>
              <button
                onClick={handleSendTestEmail}
                disabled={testEmailSending || !testEmailAddress.trim()}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {testEmailSending ? 'Sending...' : 'Send Test'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
