import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import apiClient from '../api/client';

const TIMEFRAME_PRESETS = [
  { label: '1h', hours: 1 },
  { label: '3h', hours: 3 },
  { label: '6h', hours: 6 },
  { label: '9h', hours: 9 },
  { label: '12h', hours: 12 },
  { label: 'Today', hours: 0 },
  { label: 'Yesterday', hours: -1 },
];

/**
 * RouteUptimePanel — Full uptime dashboard panel with time range selector.
 * Fetches data from the traffic report API (per-minute aggregated data).
 *
 * Props:
 *   routes     — array of { file, label, route_id } from /logs/files
 *   selectedRouteId — currently selected route_id from the log viewer (optional pre-select)
 */
export default function RouteUptimePanel({ routes = [], selectedRouteId = '' }) {
  const [routeId, setRouteId] = useState(selectedRouteId || '');
  const [activePreset, setActivePreset] = useState('Today');
  const [customDate, setCustomDate] = useState('');
  const [customTimeFrom, setCustomTimeFrom] = useState('');
  const [customTimeTo, setCustomTimeTo] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [reportData, setReportData] = useState(null);

  // Update routeId when parent selection changes
  useEffect(() => {
    if (selectedRouteId) {
      setRouteId(selectedRouteId);
    }
  }, [selectedRouteId]);

  // Auto-fetch when route changes (default: Today)
  useEffect(() => {
    if (routeId) {
      fetchWithPreset(activePreset);
    }
  }, [routeId]);

  // Helper: format local date as YYYY-MM-DD (avoids UTC shift from toISOString)
  function formatLocalDate(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  /**
   * Compute the date/time ranges for a given preset.
   * Returns an array of { date, timeFrom, timeTo } objects.
   * Most presets return a single range, but cross-midnight hour presets
   * return TWO ranges (yesterday's tail + today's head) so both days
   * are fetched and merged.
   */
  function getDateAndTimeRanges(presetLabel) {
    const now = new Date();
    const timeTo = now.toTimeString().slice(0, 5); // HH:MM local

    if (presetLabel === 'Today') {
      return [{ date: formatLocalDate(now), timeFrom: '00:00', timeTo }];
    }

    if (presetLabel === 'Yesterday') {
      const yesterday = new Date(now);
      yesterday.setDate(yesterday.getDate() - 1);
      return [{ date: formatLocalDate(yesterday), timeFrom: '00:00', timeTo: '23:59' }];
    }

    // Hour-based presets: last N hours from now
    const preset = TIMEFRAME_PRESETS.find((p) => p.label === presetLabel);
    const hours = preset?.hours || 6;
    const from = new Date(now.getTime() - hours * 60 * 60 * 1000);
    const fromDate = formatLocalDate(from);
    const toDate = formatLocalDate(now);
    const timeFrom = from.toTimeString().slice(0, 5);

    if (fromDate === toDate) {
      // Same day — single range
      return [{ date: toDate, timeFrom, timeTo }];
    }

    // Crosses midnight — need data from BOTH days:
    // 1. Yesterday from the computed start time to 23:59
    // 2. Today from 00:00 to now
    return [
      { date: fromDate, timeFrom, timeTo: '23:59' },
      { date: toDate, timeFrom: '00:00', timeTo },
    ];
  }

  // Legacy single-range helper for populating the custom fields display
  function getDateAndTimeRange(presetLabel) {
    const ranges = getDateAndTimeRanges(presetLabel);
    // Return the first range for display purposes (custom fields show primary range)
    if (ranges.length === 1) {
      return ranges[0];
    }
    // For cross-midnight: show the full span in the custom fields
    return { date: ranges[0].date, timeFrom: ranges[0].timeFrom, timeTo: ranges[1].timeTo };
  }

  async function fetchWithPreset(presetLabel) {
    if (!routeId) return;
    const ranges = getDateAndTimeRanges(presetLabel);

    if (ranges.length === 1) {
      // Single day — straightforward fetch
      await fetchReport(routeId, ranges[0].date, ranges[0].timeFrom, ranges[0].timeTo);
    } else {
      // Cross-midnight — fetch both days and merge results
      await fetchMultiDayReport(routeId, ranges);
    }
  }

  async function fetchCustomRange() {
    if (!routeId || !customDate) return;
    await fetchReport(
      routeId,
      customDate,
      customTimeFrom || '00:00',
      customTimeTo || '23:59'
    );
  }

  async function fetchReport(routeId, date, timeFrom, timeTo) {
    setLoading(true);
    setError('');
    try {
      const response = await apiClient.get('/metrics/traffic-report', {
        params: { route_id: routeId, date, time_from: timeFrom, time_to: timeTo },
        timeout: 60000,
      });
      setReportData(response.data);
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to fetch traffic report';
      setError(msg);
      setReportData(null);
    } finally {
      setLoading(false);
    }
  }

  /**
   * Fetch traffic data for multiple day ranges (cross-midnight presets)
   * and merge the results into a single reportData object.
   * Minutes from earlier days are prefixed with the date for clarity
   * in the chart (e.g. "23:45" from yesterday, "00:15" from today).
   */
  async function fetchMultiDayReport(routeId, ranges) {
    setLoading(true);
    setError('');
    try {
      const responses = await Promise.all(
        ranges.map((r) =>
          apiClient.get('/metrics/traffic-report', {
            params: { route_id: routeId, date: r.date, time_from: r.timeFrom, time_to: r.timeTo },
            timeout: 60000,
          })
        )
      );

      // Merge minutes from all responses in order.
      // To distinguish times across days, prefix with short date for earlier days.
      const mergedMinutes = [];
      let totalRequests = 0;
      let totalLatencyWeighted = 0;

      for (let i = 0; i < responses.length; i++) {
        const data = responses[i].data;
        if (!data || !data.minutes) continue;

        const isLastRange = i === responses.length - 1;
        const datePrefix = isLastRange ? '' : data.date.slice(5) + ' '; // "MM-DD " prefix for earlier days

        for (const m of data.minutes) {
          mergedMinutes.push({
            ...m,
            time: datePrefix + m.time,
          });
          totalRequests += m.count;
          totalLatencyWeighted += m.avg_latency_ms * m.count;
        }
      }

      // Build merged report object matching the single-day format
      const lastResponse = responses[responses.length - 1].data;
      const firstResponse = responses[0].data;
      const peakPerMinute = mergedMinutes.length > 0
        ? Math.max(...mergedMinutes.map((m) => m.count))
        : 0;

      setReportData({
        route_id: routeId,
        date: `${firstResponse.date} — ${lastResponse.date}`,
        time_from: firstResponse.time_from,
        time_to: lastResponse.time_to,
        total_requests: totalRequests,
        avg_latency_ms: totalRequests > 0 ? Math.round(totalLatencyWeighted / totalRequests * 10) / 10 : 0,
        peak_per_minute: peakPerMinute,
        minutes: mergedMinutes,
        pods_queried: lastResponse.pods_queried,
        log_file: lastResponse.log_file,
      });
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to fetch traffic report';
      setError(msg);
      setReportData(null);
    } finally {
      setLoading(false);
    }
  }

  function handlePresetClick(preset) {
    setActivePreset(preset.label);
    // Update custom date field to show what's being queried
    const { date, timeFrom, timeTo } = getDateAndTimeRange(preset.label);
    setCustomDate(date);
    setCustomTimeFrom(timeFrom);
    setCustomTimeTo(timeTo);
    fetchWithPreset(preset.label);
  }

  function handleApplyCustom() {
    setActivePreset('custom');
    fetchCustomRange();
  }

  // Process report data for charts
  const { chartData, stats, errorEvents, timelineSegments } = useMemo(() => {
    if (!reportData || !reportData.minutes || reportData.minutes.length === 0) {
      return { chartData: [], stats: null, errorEvents: [], timelineSegments: [] };
    }

    const minutes = reportData.minutes;
    const chartPoints = [];
    const errors = [];

    let totalRequests = 0;
    let totalLatency = 0;
    let errorRequests = 0;

    for (const m of minutes) {
      const hasErrors = Object.keys(m.statuses).some((code) => {
        const c = parseInt(code, 10);
        return c >= 400 && c <= 599;
      });

      const errorCount = Object.entries(m.statuses)
        .filter(([code]) => parseInt(code, 10) >= 400)
        .reduce((sum, [, count]) => sum + count, 0);

      const successCount = m.count - errorCount;

      chartPoints.push({
        time: m.time,
        latency: m.avg_latency_ms,
        count: m.count,
        hasErrors,
        errorCount,
        successCount,
        statuses: m.statuses,
      });

      totalRequests += m.count;
      totalLatency += m.avg_latency_ms * m.count;
      errorRequests += errorCount;

      // Collect error minutes for the table
      if (hasErrors) {
        const errorCodes = Object.entries(m.statuses)
          .filter(([code]) => parseInt(code, 10) >= 400)
          .map(([code, count]) => ({ code, count }));
        errors.push({
          time: m.time,
          errorCodes,
          totalErrors: errorCount,
          latency: m.avg_latency_ms,
        });
      }
    }

    const avgLatency = totalRequests > 0 ? Math.round(totalLatency / totalRequests) : 0;
    const uptimePercent = totalRequests > 0
      ? (((totalRequests - errorRequests) / totalRequests) * 100).toFixed(2)
      : '100.00';

    // Build timeline segments
    const segments = [];
    if (chartPoints.length > 0) {
      let currentUp = !chartPoints[0].hasErrors;
      let segStart = 0;

      for (let i = 1; i < chartPoints.length; i++) {
        const isUp = !chartPoints[i].hasErrors;
        if (isUp !== currentUp) {
          segments.push({
            startIdx: segStart,
            endIdx: i - 1,
            isUp: currentUp,
            startTime: chartPoints[segStart].time,
            endTime: chartPoints[i - 1].time,
          });
          segStart = i;
          currentUp = isUp;
        }
      }
      segments.push({
        startIdx: segStart,
        endIdx: chartPoints.length - 1,
        isUp: currentUp,
        startTime: chartPoints[segStart].time,
        endTime: chartPoints[chartPoints.length - 1].time,
      });
    }

    return {
      chartData: chartPoints,
      stats: {
        uptimePercent,
        avgLatency,
        totalRequests,
        errorRequests,
      },
      errorEvents: errors,
      timelineSegments: segments,
    };
  }, [reportData]);

  // Custom dot — red for error minutes
  function CustomDot(props) {
    const { cx, cy, payload } = props;
    if (!payload || !payload.hasErrors) return null;
    return (
      <circle cx={cx} cy={cy} r={4} fill="#ef4444" stroke="#fff" strokeWidth={1.5} />
    );
  }

  // Custom tooltip
  function CustomTooltip({ active, payload }) {
    if (!active || !payload || !payload.length) return null;
    const data = payload[0].payload;
    return (
      <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-xs">
        <p className="font-medium text-gray-900">{data.time}</p>
        <p className="text-gray-600">
          Avg Latency: <span className="font-medium">{data.latency}ms</span>
        </p>
        <p className="text-gray-600">
          Requests: <span className="font-medium">{data.count}</span>
        </p>
        {data.hasErrors && (
          <p className="text-red-600 font-medium mt-1">
            {data.errorCount} error{data.errorCount > 1 ? 's' : ''}
          </p>
        )}
        {data.statuses && (
          <div className="mt-1 text-gray-500">
            {Object.entries(data.statuses).map(([code, count]) => (
              <span key={code} className="mr-2">
                <span className={parseInt(code, 10) >= 400 ? 'text-red-600' : 'text-green-600'}>{code}</span>:{count}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Get route label for display
  const selectedRoute = routes.find((r) => r.route_id === routeId);
  const routeLabel = selectedRoute?.label || routeId;

  return (
    <div className="bg-white rounded-lg shadow mt-4">
      {/* Header with timeframe controls */}
      <div className="px-6 py-4 border-b border-gray-200">
        <div className="flex flex-wrap items-center gap-3">
          {/* Chart timeframe label */}
          <span className="text-sm font-medium text-gray-700">CHART TIMEFRAME:</span>

          {/* Preset buttons */}
          {TIMEFRAME_PRESETS.map((preset) => (
            <button
              key={preset.label}
              onClick={() => handlePresetClick(preset)}
              disabled={loading}
              className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors ${
                activePreset === preset.label
                  ? 'bg-teal-600 text-white border-teal-600'
                  : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
              } disabled:opacity-50`}
            >
              {preset.label}
            </button>
          ))}

          {/* Custom date/time inputs */}
          <input
            type="date"
            value={customDate}
            onChange={(e) => setCustomDate(e.target.value)}
            className="px-2 py-1.5 text-xs border border-gray-300 rounded-md focus:ring-2 focus:ring-teal-500 focus:outline-none"
          />
          <input
            type="time"
            value={customTimeFrom}
            onChange={(e) => setCustomTimeFrom(e.target.value)}
            placeholder="From"
            className="px-2 py-1.5 text-xs border border-gray-300 rounded-md focus:ring-2 focus:ring-teal-500 focus:outline-none w-24"
          />
          <span className="text-xs text-gray-400">to</span>
          <input
            type="time"
            value={customTimeTo}
            onChange={(e) => setCustomTimeTo(e.target.value)}
            placeholder="To"
            className="px-2 py-1.5 text-xs border border-gray-300 rounded-md focus:ring-2 focus:ring-teal-500 focus:outline-none w-24"
          />
          <button
            onClick={handleApplyCustom}
            disabled={loading || !customDate}
            className="px-3 py-1.5 text-xs font-medium text-white bg-teal-600 rounded-md hover:bg-teal-700 disabled:opacity-50 transition-colors"
          >
            Apply
          </button>

          {/* Route selector */}
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-gray-500">SERVICE:</span>
            <select
              value={routeId}
              onChange={(e) => setRouteId(e.target.value)}
              className="px-2 py-1.5 text-xs border border-gray-300 rounded-md focus:ring-2 focus:ring-teal-500 focus:outline-none min-w-[180px]"
            >
              <option value="">Select route...</option>
              {routes.map((r) => (
                <option key={r.route_id} value={r.route_id}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="flex flex-col items-center gap-3">
            <div className="animate-spin rounded-full h-8 w-8 border-4 border-teal-600 border-t-transparent"></div>
            <p className="text-sm text-gray-500">Loading traffic data...</p>
          </div>
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div className="px-6 py-4">
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{error}</div>
        </div>
      )}

      {/* No route selected */}
      {!routeId && !loading && !error && (
        <div className="px-6 py-8 text-center text-sm text-gray-500">
          Select a service above to view uptime data.
        </div>
      )}

      {/* Chart content */}
      {!loading && !error && stats && chartData.length > 0 && (
        <>
          {/* Route name + stats */}
          <div className="px-6 py-4 border-b border-gray-100">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold text-gray-900">{routeLabel}</h3>
                {reportData && (
                  <p className="text-xs text-gray-500 mt-0.5">
                    {reportData.date} {reportData.time_from} — {reportData.time_to}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-5">
                <div className="text-center">
                  <p className={`text-lg font-bold ${parseFloat(stats.uptimePercent) >= 99 ? 'text-green-600' : parseFloat(stats.uptimePercent) >= 95 ? 'text-yellow-600' : 'text-red-600'}`}>
                    {stats.uptimePercent}%
                  </p>
                  <p className="text-xs text-gray-500 uppercase">Uptime</p>
                </div>
                <div className="text-center">
                  <p className="text-lg font-bold text-gray-800">{stats.avgLatency}ms</p>
                  <p className="text-xs text-gray-500 uppercase">Avg Latency</p>
                </div>
                <div className="text-center">
                  <p className="text-lg font-bold text-gray-800">{stats.totalRequests}</p>
                  <p className="text-xs text-gray-500 uppercase">Requests</p>
                </div>
                <div className="text-center">
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    stats.errorRequests === 0 ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                  }`}>
                    {stats.errorRequests === 0 ? 'OPERATIONAL' : `${stats.errorRequests} ERRORS`}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Response Time Chart */}
          <div className="px-6 py-4">
            <p className="text-xs font-medium text-gray-500 uppercase mb-2">Response Time (ms)</p>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <defs>
                  <linearGradient id="uptimeLatencyGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="time"
                  tick={{ fontSize: 10, fill: '#6b7280' }}
                  interval="preserveStartEnd"
                  tickCount={10}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: '#6b7280' }}
                  tickFormatter={(v) => `${v}ms`}
                  width={55}
                />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="monotone"
                  dataKey="latency"
                  stroke="#10b981"
                  strokeWidth={1.5}
                  fill="url(#uptimeLatencyGradient)"
                  dot={<CustomDot />}
                  activeDot={{ r: 4, fill: '#10b981', stroke: '#fff', strokeWidth: 1.5 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Outage Timeline */}
          <div className="px-6 py-4 border-t border-gray-100">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-medium text-gray-500 uppercase">Outage Timeline</p>
              <div className="flex items-center gap-3 text-xs">
                <span className="flex items-center gap-1">
                  <span className="inline-block w-3 h-3 rounded-sm bg-green-500"></span> Up
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-3 h-3 rounded-sm bg-red-500"></span> Down
                </span>
              </div>
            </div>

            <div className="w-full h-8 rounded-md overflow-hidden flex bg-gray-100">
              {timelineSegments.map((seg, idx) => {
                const totalPoints = chartData.length;
                const segLength = seg.endIdx - seg.startIdx + 1;
                const widthPercent = (segLength / totalPoints) * 100;
                return (
                  <div
                    key={idx}
                    className={`h-full ${seg.isUp ? 'bg-green-500' : 'bg-red-500'}`}
                    style={{ width: `${widthPercent}%` }}
                    title={`${seg.isUp ? 'Up' : 'Down'}: ${seg.startTime} — ${seg.endTime}`}
                  />
                );
              })}
            </div>

            <div className="flex justify-between mt-1">
              <span className="text-xs text-gray-400">{chartData[0]?.time || ''}</span>
              <span className="text-xs text-gray-400">{chartData[chartData.length - 1]?.time || ''}</span>
            </div>

            {stats.errorRequests === 0 ? (
              <p className="text-xs text-green-600 mt-2 font-medium">No outages in this period.</p>
            ) : (
              <p className="text-xs text-red-600 mt-2 font-medium">
                {stats.errorRequests} error request{stats.errorRequests > 1 ? 's' : ''} detected in this period.
              </p>
            )}
          </div>

          {/* Error Events Table */}
          {errorEvents.length > 0 && (
            <div className="px-6 py-4 border-t border-gray-100">
              <p className="text-xs font-medium text-gray-500 uppercase mb-3">Error Events</p>
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left py-2 pr-4 font-medium text-gray-500">Time</th>
                      <th className="text-left py-2 pr-4 font-medium text-gray-500">Status Codes</th>
                      <th className="text-right py-2 pr-4 font-medium text-gray-500">Error Count</th>
                      <th className="text-right py-2 font-medium text-gray-500">Avg Latency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {errorEvents.map((evt, idx) => (
                      <tr key={idx} className="border-b border-gray-50 hover:bg-red-50">
                        <td className="py-2 pr-4 text-gray-700 whitespace-nowrap">{evt.time}</td>
                        <td className="py-2 pr-4">
                          <div className="flex flex-wrap gap-1">
                            {evt.errorCodes.map(({ code, count }) => (
                              <span key={code} className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">
                                {code} ({count})
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-2 pr-4 text-right text-red-600 font-medium">{evt.totalErrors}</td>
                        <td className="py-2 text-right text-gray-700">{evt.latency}ms</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* No data for selected range */}
      {!loading && !error && routeId && reportData && chartData.length === 0 && (
        <div className="px-6 py-8 text-center text-sm text-gray-500">
          No traffic data found for this route in the selected time range.
        </div>
      )}
    </div>
  );
}
