import { useState, useEffect } from 'react';
import apiClient from '../api/client';
import { useAuthStore } from '../store/authStore';

export default function AuditLog() {
  const role = useAuthStore((state) => state.role);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filterAction, setFilterAction] = useState('');
  const [filterUser, setFilterUser] = useState('');
  const [importResults, setImportResults] = useState(null);
  const [importing, setImporting] = useState(false);
  const [showExportOptions, setShowExportOptions] = useState(false);
  const [exportTypes, setExportTypes] = useState('');  // empty = all

  useEffect(() => {
    fetchLogs();
  }, [filterAction, filterUser]);

  async function fetchLogs() {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.append('limit', '200');
      if (filterAction) params.append('action', filterAction);
      if (filterUser) params.append('username', filterUser);

      const response = await apiClient.get(`/audit?${params.toString()}`);
      setLogs(response.data);
      setError('');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch audit logs');
    } finally {
      setLoading(false);
    }
  }

  async function handleExportBackup() {
    try {
      const params = exportTypes ? `?resource_types=${exportTypes}` : '';
      const response = await apiClient.get(`/backup/export${params}`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `apisix-backup-${new Date().toISOString().slice(0, 10)}.json`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setShowExportOptions(false);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to export backup');
    }
  }

  async function handleImportBackup(event) {
    const file = event.target.files[0];
    if (!file) return;

    setImporting(true);
    setImportResults(null);
    setError('');

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await apiClient.post('/backup/import?overwrite=true', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setImportResults(response.data);
      fetchLogs(); // Refresh audit log
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to import backup');
    } finally {
      setImporting(false);
      // Reset file input
      event.target.value = '';
    }
  }
  if (role !== 'admin') {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-gray-900">Audit Log</h1>
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 text-center">
          <p className="text-sm text-yellow-700">Admin access required to view audit logs.</p>
        </div>
      </div>
    );
  }

  const actionColors = {
    LOGIN: 'bg-blue-100 text-blue-800',
    LOGOUT: 'bg-gray-100 text-gray-800',
    CREATE: 'bg-green-100 text-green-800',
    UPDATE: 'bg-yellow-100 text-yellow-800',
    DELETE: 'bg-red-100 text-red-800',
    ROLE_CHANGE: 'bg-purple-100 text-purple-800',
    EXPORT: 'bg-indigo-100 text-indigo-800',
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Audit Log</h1>
          <p className="mt-1 text-sm text-gray-500">All user actions are recorded for compliance</p>
        </div>
        <div className="flex items-center gap-3">
          {/* Import button */}
          <label className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-700 rounded-md hover:bg-blue-800 transition-colors cursor-pointer">
            <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            {importing ? 'Importing...' : 'Import Backup'}
            <input
              type="file"
              accept=".json"
              onChange={handleImportBackup}
              className="hidden"
              disabled={importing}
            />
          </label>

          {/* Export button */}
          <div className="relative">
            <button
              onClick={() => setShowExportOptions(!showExportOptions)}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-green-700 rounded-md hover:bg-green-800 transition-colors"
            >
              <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Export Backup
              <svg className="w-3 h-3 ml-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {/* Export dropdown */}
            {showExportOptions && (
              <div className="absolute right-0 mt-2 w-64 bg-white rounded-lg shadow-lg border border-gray-200 z-10 p-4">
                <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Export Options</p>
                <div className="space-y-2 mb-3">
                  <button
                    onClick={() => { setExportTypes(''); handleExportBackup(); }}
                    className="w-full text-left px-3 py-2 text-sm rounded-md hover:bg-gray-100 transition-colors"
                  >
                    📦 Export All Resources
                  </button>
                  <button
                    onClick={() => { setExportTypes('routes'); handleExportBackup(); }}
                    className="w-full text-left px-3 py-2 text-sm rounded-md hover:bg-gray-100 transition-colors"
                  >
                    🛣️ Export Routes Only
                  </button>
                  <button
                    onClick={() => { setExportTypes('routes,services,upstreams'); handleExportBackup(); }}
                    className="w-full text-left px-3 py-2 text-sm rounded-md hover:bg-gray-100 transition-colors"
                  >
                    🔗 Export Routes + Services + Upstreams
                  </button>
                  <button
                    onClick={() => { setExportTypes('ssl'); handleExportBackup(); }}
                    className="w-full text-left px-3 py-2 text-sm rounded-md hover:bg-gray-100 transition-colors"
                  >
                    🔒 Export SSL Certificates Only
                  </button>
                </div>
                <button
                  onClick={() => setShowExportOptions(false)}
                  className="w-full text-center text-xs text-gray-400 hover:text-gray-600"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Import Results */}
      {importResults && (
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-800 mb-3">Import Results</h3>
          <div className="grid grid-cols-3 gap-3 mb-3">
            <div className="text-center p-2 bg-green-50 rounded">
              <p className="text-lg font-bold text-green-700">{importResults.filter(r => r.status === 'created' || r.status === 'updated').length}</p>
              <p className="text-xs text-green-600">Success</p>
            </div>
            <div className="text-center p-2 bg-red-50 rounded">
              <p className="text-lg font-bold text-red-700">{importResults.filter(r => r.status === 'failed').length}</p>
              <p className="text-xs text-red-600">Failed</p>
            </div>
            <div className="text-center p-2 bg-gray-50 rounded">
              <p className="text-lg font-bold text-gray-700">{importResults.filter(r => r.status === 'skipped').length}</p>
              <p className="text-xs text-gray-600">Skipped</p>
            </div>
          </div>
          <div className="max-h-48 overflow-y-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="text-gray-500">
                  <th className="text-left py-1">Type</th>
                  <th className="text-left py-1">ID</th>
                  <th className="text-left py-1">Status</th>
                  <th className="text-left py-1">Detail</th>
                </tr>
              </thead>
              <tbody>
                {importResults.map((r, i) => (
                  <tr key={i} className="border-t border-gray-100">
                    <td className="py-1">{r.resource_type}</td>
                    <td className="py-1 font-mono">{r.resource_id}</td>
                    <td className="py-1">
                      <span className={`px-1.5 py-0.5 rounded text-xs ${
                        r.status === 'created' || r.status === 'updated' ? 'bg-green-100 text-green-700' :
                        r.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-700'
                      }`}>{r.status}</span>
                    </td>
                    <td className="py-1 text-gray-500 truncate max-w-[150px]">{r.detail || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            onClick={() => setImportResults(null)}
            className="mt-3 text-xs text-gray-400 hover:text-gray-600"
          >
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md text-sm">{error}</div>
      )}

      {/* Filters */}
      <div className="flex gap-4">
        <select
          value={filterAction}
          onChange={(e) => setFilterAction(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-red-500"
        >
          <option value="">All Actions</option>
          <option value="LOGIN">Login</option>
          <option value="LOGOUT">Logout</option>
          <option value="CREATE">Create</option>
          <option value="UPDATE">Update</option>
          <option value="DELETE">Delete</option>
          <option value="ROLE_CHANGE">Role Change</option>
          <option value="EXPORT">Export</option>
        </select>
        <input
          type="text"
          value={filterUser}
          onChange={(e) => setFilterUser(e.target.value)}
          placeholder="Filter by username..."
          className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-red-500 w-48"
        />
      </div>

      {/* Log Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Timestamp</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">User</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Resource</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Details</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {loading ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">Loading...</td></tr>
              ) : logs.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">No audit entries found</td></tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {new Date(log.timestamp).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{log.username}</td>
                    <td className="px-4 py-3 text-sm">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${actionColors[log.action] || 'bg-gray-100 text-gray-800'}`}>
                        {log.action}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">
                      {log.resource_type && (
                        <span>{log.resource_type}{log.resource_id ? `/${log.resource_id}` : ''}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 max-w-[200px] truncate" title={log.details}>
                      {log.details || '—'}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                        log.status === 'success' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                      }`}>
                        {log.status}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
