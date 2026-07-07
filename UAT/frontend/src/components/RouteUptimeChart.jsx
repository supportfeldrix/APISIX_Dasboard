import { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
} from 'recharts';

/**
 * RouteUptimeChart — Displays response time chart and outage timeline
 * based on parsed log data from the Log Viewer.
 *
 * Props:
 *   logLines  — array of raw log line strings (JSON format from APISIX)
 *   fileName  — the log file name being viewed
 */
export default function RouteUptimeChart({ logLines, fileName }) {
  // Parse log lines into data points
  const { dataPoints, stats, errorEvents } = useMemo(() => {
    if (!logLines || logLines.length === 0) {
      return { dataPoints: [], stats: null, errorEvents: [] };
    }

    const points = [];
    const errors = [];

    for (const line of logLines) {
      try {
        const entry = JSON.parse(line);
        const startTime = entry.start_time;
        if (!startTime) continue;

        const ts = new Date(startTime);
        if (isNaN(ts.getTime())) continue;

        const status = entry.response?.status || 0;
        const latency = entry.latency || 0;
        const method = entry.request?.method || '';
        const uri = entry.request?.uri || '';
        const isUp = status >= 200 && status < 400;

        const point = {
          timestamp: ts.getTime(),
          time: ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          status,
          latency: Math.round(latency),
          isUp,
          method,
          uri,
        };

        points.push(point);

        // Collect error events for the table
        if (!isUp && status > 0) {
          errors.push(point);
        }
      } catch {
        // Skip non-JSON lines (nginx format, etc.)
        continue;
      }
    }

    // Sort by timestamp
    points.sort((a, b) => a.timestamp - b.timestamp);
    errors.sort((a, b) => a.timestamp - b.timestamp);

    if (points.length === 0) {
      return { dataPoints: [], stats: null, errorEvents: [] };
    }

    // Calculate stats
    const totalChecks = points.length;
    const upChecks = points.filter((p) => p.isUp).length;
    const uptimePercent = ((upChecks / totalChecks) * 100).toFixed(2);
    const avgLatency = Math.round(
      points.reduce((sum, p) => sum + p.latency, 0) / totalChecks
    );
    const maxLatency = Math.max(...points.map((p) => p.latency));

    return {
      dataPoints: points,
      stats: {
        uptimePercent,
        avgLatency,
        maxLatency,
        totalChecks,
        upChecks,
        downChecks: totalChecks - upChecks,
      },
      errorEvents: errors,
    };
  }, [logLines]);

  if (!dataPoints || dataPoints.length === 0) {
    return null; // Don't render anything if no parseable data
  }

  // Build outage timeline segments
  const timelineSegments = useMemo(() => {
    if (dataPoints.length === 0) return [];

    const segments = [];
    let currentStatus = dataPoints[0].isUp;
    let segStart = 0;

    for (let i = 1; i < dataPoints.length; i++) {
      if (dataPoints[i].isUp !== currentStatus) {
        segments.push({
          startIdx: segStart,
          endIdx: i - 1,
          isUp: currentStatus,
          startTime: dataPoints[segStart].time,
          endTime: dataPoints[i - 1].time,
        });
        segStart = i;
        currentStatus = dataPoints[i].isUp;
      }
    }
    // Final segment
    segments.push({
      startIdx: segStart,
      endIdx: dataPoints.length - 1,
      isUp: currentStatus,
      startTime: dataPoints[segStart].time,
      endTime: dataPoints[dataPoints.length - 1].time,
    });

    return segments;
  }, [dataPoints]);

  // Find indices of error points for red dots on chart
  const errorIndices = useMemo(() => {
    return dataPoints
      .map((p, idx) => (!p.isUp ? idx : -1))
      .filter((idx) => idx >= 0);
  }, [dataPoints]);

  // Custom dot renderer — shows red dots for errors
  function CustomDot(props) {
    const { cx, cy, payload } = props;
    if (!payload || payload.isUp) return null;
    return (
      <circle cx={cx} cy={cy} r={4} fill="#ef4444" stroke="#fff" strokeWidth={1.5} />
    );
  }

  // Custom tooltip for the area chart
  function CustomTooltip({ active, payload }) {
    if (!active || !payload || !payload.length) return null;
    const data = payload[0].payload;
    return (
      <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-xs">
        <p className="font-medium text-gray-900">{data.time}</p>
        <p className="text-gray-600">
          Latency: <span className="font-medium">{data.latency}ms</span>
        </p>
        <p className="text-gray-600">
          Status:{' '}
          <span className={`font-medium ${data.isUp ? 'text-green-600' : 'text-red-600'}`}>
            {data.status}
          </span>
        </p>
        {data.method && (
          <p className="text-gray-500 mt-1">{data.method} {data.uri}</p>
        )}
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow mt-4">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <svg className="h-5 w-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <h3 className="text-lg font-semibold text-gray-800">Response Time &amp; Outage Detail</h3>
          </div>

          {/* Stats badges */}
          <div className="flex items-center gap-4">
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
              <p className="text-lg font-bold text-gray-800">{stats.totalChecks}</p>
              <p className="text-xs text-gray-500 uppercase">Checks</p>
            </div>
            <div className="text-center">
              <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                stats.downChecks === 0 ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
              }`}>
                {stats.downChecks === 0 ? 'OPERATIONAL' : `${stats.downChecks} ERRORS`}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Response Time Chart */}
      <div className="px-6 py-4">
        <p className="text-xs font-medium text-gray-500 uppercase mb-2">Response Time (ms)</p>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={dataPoints} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <defs>
              <linearGradient id="latencyGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#10b981" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 10, fill: '#6b7280' }}
              interval="preserveStartEnd"
              tickCount={8}
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
              fill="url(#latencyGradient)"
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

        {/* Timeline bar */}
        <div className="w-full h-8 rounded-md overflow-hidden flex bg-gray-100">
          {timelineSegments.map((seg, idx) => {
            const totalPoints = dataPoints.length;
            const segLength = seg.endIdx - seg.startIdx + 1;
            const widthPercent = (segLength / totalPoints) * 100;

            return (
              <div
                key={idx}
                className={`h-full transition-all ${seg.isUp ? 'bg-green-500' : 'bg-red-500'}`}
                style={{ width: `${widthPercent}%` }}
                title={`${seg.isUp ? 'Up' : 'Down'}: ${seg.startTime} — ${seg.endTime} (${segLength} requests)`}
              />
            );
          })}
        </div>

        {/* Timeline labels */}
        <div className="flex justify-between mt-1">
          <span className="text-xs text-gray-400">{dataPoints[0]?.time || ''}</span>
          <span className="text-xs text-gray-400">{dataPoints[dataPoints.length - 1]?.time || ''}</span>
        </div>

        {/* Outage summary */}
        {stats.downChecks === 0 ? (
          <p className="text-xs text-green-600 mt-2 font-medium">No outages in this period.</p>
        ) : (
          <p className="text-xs text-red-600 mt-2 font-medium">
            {stats.downChecks} error response{stats.downChecks > 1 ? 's' : ''} detected in this period.
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
                  <th className="text-left py-2 pr-4 font-medium text-gray-500">Status</th>
                  <th className="text-left py-2 pr-4 font-medium text-gray-500">Method</th>
                  <th className="text-left py-2 pr-4 font-medium text-gray-500">URI</th>
                  <th className="text-right py-2 font-medium text-gray-500">Latency</th>
                </tr>
              </thead>
              <tbody>
                {errorEvents.map((evt, idx) => (
                  <tr key={idx} className="border-b border-gray-50 hover:bg-red-50">
                    <td className="py-2 pr-4 text-gray-700 whitespace-nowrap">{evt.time}</td>
                    <td className="py-2 pr-4">
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">
                        {evt.status}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-gray-600 font-medium">{evt.method}</td>
                    <td className="py-2 pr-4 text-gray-600 max-w-[300px] truncate" title={evt.uri}>
                      {evt.uri}
                    </td>
                    <td className="py-2 text-right text-gray-700">{evt.latency}ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
