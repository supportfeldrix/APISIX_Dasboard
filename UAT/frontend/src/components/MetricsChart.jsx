import React from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

const POD_COLORS = [
  '#3b82f6', // blue
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // violet
  '#06b6d4', // cyan
  '#f97316', // orange
  '#ec4899', // pink
];

/**
 * MetricsChart component that renders CPU and Memory area charts per pod.
 * @param {{ data: Array<{ pod: string, cpu_usage: number, memory_bytes: number }> }} props
 */
function MetricsChart({ data }) {
  if (!data || data.length === 0) {
    return (
      <div className="text-center text-gray-500 py-8">
        No metrics data available
      </div>
    );
  }

  // Extract unique pod names
  const pods = [...new Set(data.map((item) => item.pod))];

  // Transform data for Recharts: group by index/timestamp with pod values as keys
  // Each entry becomes { index, pod1_cpu, pod2_cpu, ... }
  const cpuData = data.map((item, idx) => ({
    name: item.pod,
    index: idx,
    cpu_usage: item.cpu_usage,
  }));

  const memoryData = data.map((item, idx) => ({
    name: item.pod,
    index: idx,
    memory_bytes: item.memory_bytes,
  }));

  // Group data by pod for stacked view
  const groupedCpuData = pods.map((pod) => {
    const podMetrics = data.filter((item) => item.pod === pod);
    return { pod, metrics: podMetrics };
  });

  // Create chart-friendly format: one entry per pod
  const cpuChartData = pods.map((pod, idx) => {
    const podItem = data.find((item) => item.pod === pod);
    return {
      pod,
      cpu_usage: podItem ? podItem.cpu_usage : 0,
    };
  });

  const memoryChartData = pods.map((pod, idx) => {
    const podItem = data.find((item) => item.pod === pod);
    return {
      pod,
      memory_bytes: podItem ? podItem.memory_bytes : 0,
    };
  });

  return (
    <div className="space-y-8">
      {/* CPU Usage Chart */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">
          CPU Usage per Pod
        </h3>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={cpuChartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="pod" tick={{ fontSize: 12 }} />
              <YAxis
                tick={{ fontSize: 12 }}
                label={{
                  value: 'CPU (cores)',
                  angle: -90,
                  position: 'insideLeft',
                  style: { fontSize: 12 },
                }}
              />
              <Tooltip />
              <Legend />
              <Area
                type="monotone"
                dataKey="cpu_usage"
                name="CPU Usage"
                stroke={POD_COLORS[0]}
                fill={POD_COLORS[0]}
                fillOpacity={0.3}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Memory Usage Chart */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">
          Memory Usage per Pod
        </h3>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={memoryChartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="pod" tick={{ fontSize: 12 }} />
              <YAxis
                tick={{ fontSize: 12 }}
                tickFormatter={(value) => {
                  if (value >= 1073741824) return `${(value / 1073741824).toFixed(1)} GB`;
                  if (value >= 1048576) return `${(value / 1048576).toFixed(0)} MB`;
                  if (value >= 1024) return `${(value / 1024).toFixed(0)} KB`;
                  return `${value} B`;
                }}
                label={{
                  value: 'Memory',
                  angle: -90,
                  position: 'insideLeft',
                  style: { fontSize: 12 },
                }}
              />
              <Tooltip
                formatter={(value) => {
                  if (value >= 1073741824) return `${(value / 1073741824).toFixed(2)} GB`;
                  if (value >= 1048576) return `${(value / 1048576).toFixed(1)} MB`;
                  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
                  return `${value} B`;
                }}
              />
              <Legend />
              <Area
                type="monotone"
                dataKey="memory_bytes"
                name="Memory"
                stroke={POD_COLORS[1]}
                fill={POD_COLORS[1]}
                fillOpacity={0.3}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

export default MetricsChart;
