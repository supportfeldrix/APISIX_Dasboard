import { useState, useEffect, useRef } from 'react';
import apiClient from '../api/client';
import RouteUptimeChart from '../components/RouteUptimeChart';
import RouteUptimePanel from '../components/RouteUptimePanel';

export default function Logs() {
  const [logFiles, setLogFiles] = useState([]);
  const [pods, setPods] = useState([]);
  const [selectedFile, setSelectedFile] = useState('');
  const [selectedPod, setSelectedPod] = useState('');
  const [lines, setLines] = useState(100);
  const [search, setSearch] = useState('');
  const [logData, setLogData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [rawView, setRawView] = useState(false);
  const logContainerRef = useRef(null);
  const intervalRef = useRef(null);

  useEffect(() => {
    fetchLogFiles();
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  useEffect(() => {
    if (autoRefresh && selectedFile && selectedPod) {
      intervalRef.current = setInterval(fetchLogs, 5000);
      return () => clearInterval(intervalRef.current);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
  }, [autoRefresh, selectedFile, selectedPod, lines, search]);

  async function fetchLogFiles() {
    try {
      const response = await apiClient.get('/logs/files');
      setLogFiles(response.data.files || []);
      setPods(response.data.pods || []);
      if (response.data.pods?.length > 0) setSelectedPod(response.data.pods[0]);
      if (response.data.files?.length > 0) setSelectedFile(response.data.files[0].file);
    } catch (err) {
      setError('Failed to load log file list');
    }
  }

  async function fetchLogs() {
    if (!selectedFile || !selectedPod) return;
    setLoading(true);
    setError('');
    try {
      const params = { file: selectedFile, pod: selectedPod, lines };
      if (search.trim()) params.search = search.trim();
      const response = await apiClient.get('/logs/view', { params });
      setLogData(response.data);
      // Auto-scroll to bottom
      setTimeout(() => {
        if (logContainerRef.current) {
          logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
        }
      }, 50);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch logs');
    } finally {
      setLoading(false);
    }
  }

  function formatLogLine(line) {
    // Try to parse JSON and format nicely
    try {
      const entry = JSON.parse(line);
      const ts = entry.start_time ? new Date(entry.start_time).toLocaleTimeString() : '';
      const status = entry.response?.status || '';
      const method = entry.request?.method || '';
      const uri = entry.request?.uri || '';
      const latency = entry.latency ? `${Math.round(entry.latency)}ms` : '';
      const statusColor = status >= 500 ? 'text-red-400' : status >= 400 ? 'text-yellow-400' : 'text-green-400';
      return (
        <span>
          <span className="text-gray-500">{ts}</span>{' '}
          <span className={statusColor}>{status}</span>{' '}
          <span className="text-blue-400">{method}</span>{' '}
          <span className="text-gray-300">{uri}</span>{' '}
          <span className="text-purple-400">{latency}</span>
        </span>
      );
    } catch {
      // Not JSON — return as-is (nginx format)
      return <span className="text-gray-300">{line}</span>;
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Log Viewer</h1>
        <span className="text-sm text-gray-500">
          View APISIX route logs in real-time
        </span>
      </div>

      {/* Controls */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Log File</label>
            <select
              value={selectedFile}
              onChange={(e) => setSelectedFile(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none min-w-[200px]"
            >
              {logFiles.map((f) => (
                <option key={f.file} value={f.file}>{f.label} ({f.file})</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Pod</label>
            <select
              value={selectedPod}
              onChange={(e) => setSelectedPod(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            >
              {pods.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Lines</label>
            <select
              value={lines}
              onChange={(e) => setLines(Number(e.target.value))}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            >
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
              <option value={500}>500</option>
              <option value={1000}>1000</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Search / Filter</label>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="e.g. 404, error, route_id..."
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none min-w-[200px]"
              onKeyDown={(e) => { if (e.key === 'Enter') fetchLogs(); }}
            />
          </div>

          <button
            onClick={fetchLogs}
            disabled={loading || !selectedFile || !selectedPod}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Loading...' : 'Fetch Logs'}
          </button>

          <div className="flex items-center gap-2">
            <button
              type="button"
              role="switch"
              aria-checked={autoRefresh}
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                autoRefresh ? 'bg-green-500' : 'bg-gray-200'
              }`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                autoRefresh ? 'translate-x-6' : 'translate-x-1'
              }`} />
            </button>
            <span className="text-xs text-gray-600">Auto-refresh (5s)</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              role="switch"
              aria-checked={rawView}
              onClick={() => setRawView(!rawView)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                rawView ? 'bg-indigo-500' : 'bg-gray-200'
              }`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                rawView ? 'translate-x-6' : 'translate-x-1'
              }`} />
            </button>
            <span className="text-xs text-gray-600">Raw JSON</span>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{error}</div>
      )}

      {/* Log Output */}
      {logData && (
        <div className="bg-gray-900 rounded-lg shadow overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
            <span className="text-xs text-gray-400">
              {logData.pod}:{logData.file} — {logData.total} lines
              {logData.search && ` (filtered: "${logData.search}")`}
            </span>
            {autoRefresh && (
              <span className="inline-flex items-center gap-1 text-xs text-green-400">
                <span className="h-2 w-2 rounded-full bg-green-400 animate-pulse"></span>
                Live
              </span>
            )}
          </div>
          <div
            ref={logContainerRef}
            className="p-4 overflow-x-auto overflow-y-auto max-h-[600px] font-mono text-xs leading-relaxed"
          >
            {logData.lines.length === 0 ? (
              <p className="text-gray-500">No log entries found</p>
            ) : (
              logData.lines.map((line, i) => (
                <div key={i} className="py-0.5 hover:bg-gray-800 border-b border-gray-800">
                  <span className="text-gray-600 select-none mr-3">{String(i + 1).padStart(4)}</span>
                  {rawView ? (
                    <span className="text-gray-300 whitespace-pre-wrap break-all">{line}</span>
                  ) : (
                    formatLogLine(line)
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Route Uptime Panel — time-range based (traffic report API) */}
      <RouteUptimePanel
        routes={logFiles}
        selectedRouteId={logFiles.find((f) => f.file === selectedFile)?.route_id || ''}
      />

      {/* Route Uptime Chart — from fetched log lines (quick view) */}
      {logData && logData.lines.length > 0 && (
        <RouteUptimeChart logLines={logData.lines} fileName={logData.file} />
      )}
    </div>
  );
}
