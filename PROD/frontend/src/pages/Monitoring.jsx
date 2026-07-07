import React, { useState, useEffect } from 'react';
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import useMetrics from '../hooks/useMetrics';
import apiClient from '../api/client';

function Monitoring() {
  const { metrics, loading, error, lastUpdated } = useMetrics();
  const [pods, setPods] = useState([]);
  const [podMetrics, setPodMetrics] = useState([]);
  const [podsLoading, setPodsLoading] = useState(true);
  const [podsError, setPodsError] = useState(null);
  const [restartTarget, setRestartTarget] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [restartingPods, setRestartingPods] = useState(new Set());
  const [routeMetrics, setRouteMetrics] = useState([]);
  const [routeMetricsLoading, setRouteMetricsLoading] = useState(true);
  const [trafficReport, setTrafficReport] = useState(null);
  const [trafficLoading, setTrafficLoading] = useState(false);
  const [trafficRoute, setTrafficRoute] = useState('');
  const [trafficDate, setTrafficDate] = useState(new Date().toISOString().slice(0, 10));
  const [trafficTimeFrom, setTrafficTimeFrom] = useState('00:00');
  const [trafficTimeTo, setTrafficTimeTo] = useState('23:59');
  const [reportRoutes, setReportRoutes] = useState([]);

  useEffect(() => {
    fetchPods();
    fetchRouteMetrics();
    fetchReportRoutes();
    const interval = setInterval(() => { fetchPods(); fetchRouteMetrics(); }, 30000);
    return () => clearInterval(interval);
  }, []);

  async function fetchPods() {
    try {
      const [podsRes, metricsRes] = await Promise.all([
        apiClient.get('/pods'),
        apiClient.get('/pods/metrics').catch(() => ({ data: { pod_metrics: [] } })),
      ]);
      setPods(podsRes.data.pods || []);
      setPodMetrics(metricsRes.data.pod_metrics || []);
      setPodsError(null);
    } catch (err) {
      setPodsError(err.response?.data?.detail || err.message || 'Failed to fetch pods');
    } finally {
      setPodsLoading(false);
    }
  }

  async function fetchRouteMetrics() {
    try {
      const response = await apiClient.get('/metrics/routes');
      setRouteMetrics(response.data.routes || []);
    } catch (err) {
      console.error('Failed to fetch route metrics:', err);
    } finally {
      setRouteMetricsLoading(false);
    }
  }

  function handleDownloadCsv() {
    // Use axios to download CSV with auth headers
    apiClient.get('/metrics/routes/csv', { responseType: 'blob' })
      .then((response) => {
        const blob = new Blob([response.data], { type: 'text/csv' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `route_metrics_${new Date().toISOString().slice(0, 19).replace(/[:-]/g, '')}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
      })
      .catch((err) => {
        setPodsError(err.response?.data?.detail || 'CSV download failed');
      });
  }

  async function fetchReportRoutes() {
    try {
      const response = await apiClient.get('/metrics/traffic-report/routes');
      setReportRoutes(response.data.routes || []);
    } catch (err) {
      console.error('Failed to fetch report routes:', err);
    }
  }

  async function handleGenerateReport() {
    if (!trafficRoute || !trafficDate) return;
    setTrafficLoading(true);
    setTrafficReport(null);
    try {
      const response = await apiClient.get('/metrics/traffic-report', {
        params: {
          route_id: trafficRoute,
          date: trafficDate,
          time_from: trafficTimeFrom,
          time_to: trafficTimeTo,
        },
      });
      setTrafficReport(response.data);
    } catch (err) {
      setPodsError(err.response?.data?.detail || 'Failed to generate traffic report');
    } finally {
      setTrafficLoading(false);
    }
  }

  function handleDownloadTrafficCsv() {
    if (!trafficRoute || !trafficDate) return;
    apiClient.get('/metrics/traffic-report/csv', {
      params: {
        route_id: trafficRoute,
        date: trafficDate,
        time_from: trafficTimeFrom,
        time_to: trafficTimeTo,
      },
      responseType: 'blob',
    })
      .then((response) => {
        const blob = new Blob([response.data], { type: 'text/csv' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `traffic_report_${trafficRoute}_${trafficDate}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
      })
      .catch((err) => {
        setPodsError(err.response?.data?.detail || 'Traffic CSV download failed');
      });
  }

  // Merge pod info with metrics
  const podData = pods.map((pod) => {
    const metric = podMetrics.find((m) => m.name === pod.name);
    return { ...pod, metric };
  });

  async function handleRestartPod() {
    if (!restartTarget) return;
    const podName = restartTarget;
    setRestartTarget(null);
    setRestartingPods((prev) => new Set([...prev, podName]));
    try {
      await apiClient.delete(`/pods/${podName}`);
      setPodsError(null);
      // Wait a moment then refresh the pod list
      setTimeout(fetchPods, 3000);
    } catch (err) {
      setPodsError(err.response?.data?.detail || err.message || 'Failed to restart pod');
    } finally {
      setRestartingPods((prev) => {
        const next = new Set(prev);
        next.delete(podName);
        return next;
      });
    }
  }

  async function handleDeletePod() {
    if (!deleteTarget) return;
    const podName = deleteTarget;
    setDeleteTarget(null);
    setRestartingPods((prev) => new Set([...prev, podName]));
    try {
      await apiClient.delete(`/pods/${podName}`);
      setPodsError(null);
      // Refresh immediately since the pod won't be recreated
      setTimeout(fetchPods, 2000);
    } catch (err) {
      setPodsError(err.response?.data?.detail || err.message || 'Failed to delete pod');
    } finally {
      setRestartingPods((prev) => {
        const next = new Set(prev);
        next.delete(podName);
        return next;
      });
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex flex-col items-center space-y-4">
          <div className="animate-spin rounded-full h-12 w-12 border-4 border-red-600 border-t-transparent"></div>
          <p className="text-gray-600 text-sm">Loading metrics...</p>
        </div>
      </div>
    );
  }

  const apisix = metrics?.apisix || {};
  const connections = apisix.connections || {};
  const httpStatus = apisix.http_status || {};
  const bandwidth = apisix.bandwidth || {};

  // Prepare chart data
  const connectionData = Object.entries(connections).map(([state, value]) => ({
    name: state,
    value: value,
  }));

  const statusData = Object.entries(httpStatus).map(([code, count]) => ({
    name: `HTTP ${code}`,
    count: count,
  }));

  const bandwidthData = Object.entries(bandwidth).map(([key, bytes]) => ({
    name: key,
    mb: parseFloat((bytes / (1024 * 1024)).toFixed(2)),
  }));

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Monitoring</h1>
        {lastUpdated && (
          <span className="text-sm text-gray-500">
            Last updated: {lastUpdated.toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center">
            <svg className="h-5 w-5 text-red-400 mr-2" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
            <p className="text-sm text-red-700">
              <span className="font-medium">Error:</span> {error}
            </p>
          </div>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-lg shadow p-5">
          <p className="text-sm text-gray-500">Total HTTP Requests</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">
            {(apisix.http_requests_total || 0).toLocaleString()}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-5">
          <p className="text-sm text-gray-500">Active Connections</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">
            {connections.active || 0}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-5">
          <p className="text-sm text-gray-500">Waiting Connections</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">
            {connections.waiting || 0}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-5">
          <p className="text-sm text-gray-500">etcd Reachable</p>
          <p className={`text-2xl font-bold mt-1 ${apisix.etcd_reachable === 1 ? 'text-green-600' : 'text-red-600'}`}>
            {apisix.etcd_reachable === 1 ? 'Yes' : 'No'}
          </p>
        </div>
      </div>

      {/* Connection States Chart */}
      {connectionData.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Nginx Connections by State</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={connectionData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="value" name="Connections" fill="#dc2626" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* HTTP Status Codes */}
      {statusData.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">HTTP Response Status Codes</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statusData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" name="Requests" fill="#4f46e5" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Bandwidth */}
      {bandwidthData.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Bandwidth (MB)</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={bandwidthData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} angle={-20} textAnchor="end" height={60} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip formatter={(value) => `${value} MB`} />
                <Bar dataKey="mb" name="MB" fill="#059669" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Pod Resource Usage Chart */}
      {podMetrics.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Pod CPU &amp; Memory Usage</h3>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={podMetrics.map((pm) => ({
                name: pm.name.length > 20 ? pm.name.slice(0, 20) + '...' : pm.name,
                'CPU (millicores)': pm.total_cpu_millicores,
                'Memory (Mi)': pm.total_memory_mi,
              }))}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} angle={-15} textAnchor="end" height={70} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="CPU (millicores)" fill="#dc2626" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Memory (Mi)" fill="#4f46e5" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Route Traffic Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-800">Route Traffic</h3>
          <button
            onClick={handleDownloadCsv}
            className="inline-flex items-center px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-colors"
            title="Download route metrics as CSV"
          >
            <svg className="h-4 w-4 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export CSV
          </button>
        </div>

        {routeMetricsLoading ? (
          <div className="px-6 py-8 text-center text-gray-500">Loading route metrics...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Route</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Total Hits</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">2xx</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">4xx</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">5xx</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Success Rate</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {routeMetrics.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-500">
                      No route traffic data available
                    </td>
                  </tr>
                ) : (
                  routeMetrics.map((route) => {
                    const successRate = route.total_requests > 0
                      ? ((route.success_count / route.total_requests) * 100).toFixed(1)
                      : '0.0';
                    return (
                      <tr key={route.route_id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm">
                          <div className="font-medium text-gray-900">{route.route_name}</div>
                          <div className="text-xs text-gray-500">ID: {route.route_id}</div>
                        </td>
                        <td className="px-4 py-3 text-sm text-right font-semibold text-gray-900">
                          {route.total_requests.toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-sm text-right text-green-700">
                          {route.success_count.toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-sm text-right text-yellow-700">
                          {(route.error_count - (Object.entries(route.by_status).filter(([k]) => k.startsWith('5')).reduce((s, [, v]) => s + v, 0))).toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-sm text-right text-red-700">
                          {Object.entries(route.by_status).filter(([k]) => k.startsWith('5')).reduce((s, [, v]) => s + v, 0).toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-sm text-right">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            parseFloat(successRate) >= 99 ? 'bg-green-100 text-green-800' :
                            parseFloat(successRate) >= 95 ? 'bg-yellow-100 text-yellow-800' :
                            'bg-red-100 text-red-800'
                          }`}>
                            {successRate}%
                          </span>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Traffic Report Section */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-lg font-semibold text-gray-800">Traffic Report (Per Minute)</h3>
          <p className="text-sm text-gray-500 mt-1">Generate per-minute request counts from APISIX access logs for audit/business reporting</p>
        </div>

        <div className="px-6 py-4 space-y-4">
          {/* Filters */}
          <div className="flex flex-wrap gap-3 items-end">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Route</label>
              <select
                value={trafficRoute}
                onChange={(e) => setTrafficRoute(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none min-w-[220px]"
              >
                <option value="">Select route...</option>
                {reportRoutes.map((r) => (
                  <option key={r.route_id} value={r.route_id}>
                    {r.name || r.route_id} ({r.log_file})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Date</label>
              <input
                type="date"
                value={trafficDate}
                onChange={(e) => setTrafficDate(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">From</label>
              <input
                type="time"
                value={trafficTimeFrom}
                onChange={(e) => setTrafficTimeFrom(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">To</label>
              <input
                type="time"
                value={trafficTimeTo}
                onChange={(e) => setTrafficTimeTo(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              />
            </div>
            <button
              onClick={handleGenerateReport}
              disabled={trafficLoading || !trafficRoute || !trafficDate}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {trafficLoading ? 'Loading...' : 'Generate Report'}
            </button>
            {trafficReport && trafficReport.total_requests > 0 && (
              <button
                onClick={handleDownloadTrafficCsv}
                className="inline-flex items-center px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-colors"
              >
                <svg className="h-4 w-4 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Export CSV
              </button>
            )}
          </div>

          {/* Report Results */}
          {trafficLoading && (
            <div className="py-8 text-center text-gray-500">
              <div className="animate-spin rounded-full h-8 w-8 border-4 border-indigo-600 border-t-transparent mx-auto mb-3"></div>
              Reading logs from APISIX pods...
            </div>
          )}

          {trafficReport && !trafficLoading && (
            <div className="space-y-4">
              {/* Summary Cards */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500">Total Requests</p>
                  <p className="text-xl font-bold text-gray-900">{trafficReport.total_requests.toLocaleString()}</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500">Peak Per Minute</p>
                  <p className="text-xl font-bold text-gray-900">{trafficReport.peak_per_minute.toLocaleString()}</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500">Avg Latency</p>
                  <p className="text-xl font-bold text-gray-900">{trafficReport.avg_latency_ms} ms</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500">Active Minutes</p>
                  <p className="text-xl font-bold text-gray-900">{trafficReport.minutes.length}</p>
                </div>
              </div>

              {/* Per-Minute Table */}
              {trafficReport.minutes.length > 0 ? (
                <div className="overflow-x-auto max-h-96 overflow-y-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50 sticky top-0">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Requests</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Avg Latency (ms)</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">2xx</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">4xx</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">5xx</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {trafficReport.minutes.map((m) => {
                        const s = m.statuses || {};
                        const c2 = Object.entries(s).filter(([k]) => k.startsWith('2')).reduce((a, [, v]) => a + v, 0);
                        const c4 = Object.entries(s).filter(([k]) => k.startsWith('4')).reduce((a, [, v]) => a + v, 0);
                        const c5 = Object.entries(s).filter(([k]) => k.startsWith('5')).reduce((a, [, v]) => a + v, 0);
                        return (
                          <tr key={m.time} className="hover:bg-gray-50">
                            <td className="px-4 py-2 text-sm font-mono text-gray-900">{m.time}</td>
                            <td className="px-4 py-2 text-sm text-right font-semibold">{m.count}</td>
                            <td className="px-4 py-2 text-sm text-right text-gray-600">{m.avg_latency_ms}</td>
                            <td className="px-4 py-2 text-sm text-right text-green-700">{c2 || '—'}</td>
                            <td className="px-4 py-2 text-sm text-right text-yellow-700">{c4 || '—'}</td>
                            <td className="px-4 py-2 text-sm text-right text-red-700">{c5 || '—'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-sm text-gray-500 text-center py-4">No requests found for this route on {trafficDate} between {trafficTimeFrom} and {trafficTimeTo}</p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Pods Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-lg font-semibold text-gray-800">
            Pods in Namespace: <span className="text-red-700">cro-apisix-prod</span>
          </h3>
        </div>

        {podsError && (
          <div className="px-6 py-3 bg-yellow-50 border-b border-yellow-200 text-sm text-yellow-700">
            {podsError}
          </div>
        )}

        {podsLoading ? (
          <div className="px-6 py-8 text-center text-gray-500">Loading pods...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Pod Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">CPU (m)</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Memory (Mi)</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Restarts</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Node</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">IP</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {podData.map((pod) => (
                  <tr key={pod.name} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{pod.name}</td>
                    <td className="px-4 py-3 text-sm">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        pod.phase === 'Running' ? 'bg-green-100 text-green-800' :
                        pod.phase === 'Pending' ? 'bg-yellow-100 text-yellow-800' :
                        'bg-red-100 text-red-800'
                      }`}>
                        {pod.phase}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">
                      {pod.metric ? pod.metric.total_cpu_millicores : '—'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">
                      {pod.metric ? pod.metric.total_memory_mi : '—'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">
                      {pod.container_statuses?.reduce((sum, cs) => sum + (cs.restarts || 0), 0) || 0}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 truncate max-w-[200px]" title={pod.node}>
                      {pod.node ? pod.node.split('.')[0] : '—'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">{pod.ip || '—'}</td>
                    <td className="px-4 py-3 text-sm">
                      <div className="flex items-center gap-2">
                        {pod.phase === 'Running' && (
                          <button
                            onClick={() => setRestartTarget(pod.name)}
                            disabled={restartingPods.has(pod.name)}
                            className="inline-flex items-center px-2.5 py-1 text-xs font-medium text-red-700 bg-red-50 border border-red-200 rounded-md hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                            title={`Restart pod ${pod.name}`}
                          >
                            {restartingPods.has(pod.name) ? (
                              <>
                                <svg className="animate-spin h-3 w-3 mr-1" fill="none" viewBox="0 0 24 24">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                                </svg>
                                Restarting
                              </>
                            ) : (
                              <>
                                <svg className="h-3 w-3 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                </svg>
                                Restart
                              </>
                            )}
                          </button>
                        )}
                        {(pod.phase === 'Succeeded' || pod.phase === 'Failed') && (
                          <button
                            onClick={() => setDeleteTarget(pod.name)}
                            disabled={restartingPods.has(pod.name)}
                            className="inline-flex items-center px-2.5 py-1 text-xs font-medium text-gray-700 bg-gray-50 border border-gray-300 rounded-md hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                            title={`Delete pod ${pod.name}`}
                          >
                            {restartingPods.has(pod.name) ? (
                              <>
                                <svg className="animate-spin h-3 w-3 mr-1" fill="none" viewBox="0 0 24 24">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                                </svg>
                                Deleting
                              </>
                            ) : (
                              <>
                                <svg className="h-3 w-3 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                </svg>
                                Delete
                              </>
                            )}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {podData.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-500">
                      No pods found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Restart Confirmation Dialog */}
      {restartTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black bg-opacity-50" onClick={() => setRestartTarget(null)} />
          <div className="relative z-10 bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <div className="flex items-center mb-4">
              <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                <svg className="h-5 w-5 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
              </div>
              <h3 className="ml-3 text-lg font-semibold text-gray-900">Restart Pod</h3>
            </div>
            <p className="text-sm text-gray-600 mb-1">Are you sure you want to restart this pod?</p>
            <p className="text-sm font-mono text-gray-800 bg-gray-100 px-3 py-2 rounded mb-4 break-all">{restartTarget}</p>
            <p className="text-xs text-gray-500 mb-5">The pod will be deleted and its controller will create a new one.</p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setRestartTarget(null)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400"
              >
                Cancel
              </button>
              <button
                onClick={handleRestartPod}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-md hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500"
              >
                Restart Pod
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black bg-opacity-50" onClick={() => setDeleteTarget(null)} />
          <div className="relative z-10 bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <div className="flex items-center mb-4">
              <div className="flex-shrink-0 w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center">
                <svg className="h-5 w-5 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </div>
              <h3 className="ml-3 text-lg font-semibold text-gray-900">Delete Pod</h3>
            </div>
            <p className="text-sm text-gray-600 mb-1">Delete this completed/failed build pod?</p>
            <p className="text-sm font-mono text-gray-800 bg-gray-100 px-3 py-2 rounded mb-4 break-all">{deleteTarget}</p>
            <p className="text-xs text-gray-500 mb-5">This will permanently remove the pod. Build pods are not recreated by a controller.</p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteTarget(null)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400"
              >
                Cancel
              </button>
              <button
                onClick={handleDeletePod}
                className="px-4 py-2 text-sm font-medium text-white bg-gray-700 rounded-md hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-gray-500"
              >
                Delete Pod
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Monitoring;
