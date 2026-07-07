import { useState, useEffect } from 'react';
import apiClient from '../api/client';
import VersionBanner from '../components/VersionBanner';

export default function SystemInfo() {
  const [info, setInfo] = useState(null);
  const [deps, setDeps] = useState(null);
  const [changelog, setChangelog] = useState(null);
  const [versionCheck, setVersionCheck] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState('overview');

  useEffect(() => {
    fetchAll();
  }, []);

  async function fetchAll() {
    setLoading(true);
    try {
      const [infoRes, depsRes, changelogRes] = await Promise.all([
        apiClient.get('/system/info'),
        apiClient.get('/system/dependencies'),
        apiClient.get('/system/changelog'),
      ]);
      setInfo(infoRes.data);
      setDeps(depsRes.data);
      setChangelog(changelogRes.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch system info');
    } finally {
      setLoading(false);
    }

    // Fetch version check independently — don't block page load on failure
    try {
      const versionRes = await apiClient.get('/system/version-check');
      setVersionCheck(versionRes.data);
    } catch (err) {
      // Version check is non-critical; leave versionCheck as null (shows unavailable state)
      console.warn('Version check fetch failed:', err.message);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-10 w-10 border-4 border-red-600 border-t-transparent"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>
    );
  }

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'dependencies', label: 'Dependencies' },
    { id: 'changelog', label: 'Changelog' },
  ];

  return (
    <div className="space-y-6">
      {/* Version Check Banner */}
      <VersionBanner data={versionCheck} />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">System Information</h1>
          <p className="mt-1 text-sm text-gray-500">
            Version, dependencies, and audit information
          </p>
        </div>
        <span className="inline-flex items-center px-4 py-2 rounded-full text-sm font-bold bg-red-100 text-red-800">
          v{info?.application?.version || '—'}
        </span>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-red-700 text-red-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && info && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Application Info */}
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
              <svg className="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Application
            </h3>
            <dl className="space-y-3">
              {Object.entries(info.application).map(([key, value]) => (
                <div key={key} className="flex justify-between">
                  <dt className="text-sm text-gray-500 capitalize">{key.replace(/_/g, ' ')}</dt>
                  <dd className="text-sm font-medium text-gray-900">{value}</dd>
                </div>
              ))}
            </dl>
          </div>

          {/* Runtime Info */}
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
              <svg className="w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              Runtime
            </h3>
            <dl className="space-y-3">
              {Object.entries(info.runtime).map(([key, value]) => (
                <div key={key} className="flex justify-between">
                  <dt className="text-sm text-gray-500 capitalize">{key.replace(/_/g, ' ')}</dt>
                  <dd className="text-sm font-medium text-gray-900 truncate max-w-[250px]" title={value}>{value}</dd>
                </div>
              ))}
            </dl>
          </div>

          {/* Integrations */}
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
              <svg className="w-5 h-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              Integrations
            </h3>
            <dl className="space-y-3">
              {Object.entries(info.integrations).map(([key, value]) => (
                <div key={key} className="flex justify-between">
                  <dt className="text-sm text-gray-500 capitalize">{key.replace(/_/g, ' ')}</dt>
                  <dd className="text-sm font-medium text-gray-900 truncate max-w-[250px]" title={String(value)}>
                    {String(value)}
                  </dd>
                </div>
              ))}
            </dl>
          </div>

          {/* Security */}
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
              <svg className="w-5 h-5 text-yellow-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
              Security Configuration
            </h3>
            <dl className="space-y-3">
              {Object.entries(info.security).map(([key, value]) => (
                <div key={key} className="flex justify-between">
                  <dt className="text-sm text-gray-500 capitalize">{key.replace(/_/g, ' ')}</dt>
                  <dd className="text-sm font-medium text-gray-900">{String(value)}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      )}

      {/* Dependencies Tab */}
      {activeTab === 'dependencies' && deps && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-800">Backend Dependencies</h3>
            <span className="text-xs text-gray-500">
              Python {deps.python_version} • Last checked: {new Date(deps.last_checked).toLocaleString()}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Package</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Version</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {deps.backend_dependencies.map((pkg, idx) => (
                  <tr key={idx} className="hover:bg-gray-50">
                    <td className="px-6 py-3 text-sm font-medium text-gray-900">{pkg.name}</td>
                    <td className="px-6 py-3 text-sm text-gray-700 font-mono">{pkg.version}</td>
                    <td className="px-6 py-3 text-sm">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        Installed
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-6 py-4 bg-gray-50 border-t border-gray-200">
            <p className="text-xs text-gray-500">
              To update dependencies for security patches, run: <code className="bg-gray-200 px-1 py-0.5 rounded">pip install --upgrade -r requirements.txt</code>
            </p>
          </div>
        </div>
      )}

      {/* Changelog Tab */}
      {activeTab === 'changelog' && changelog && (
        <div className="space-y-4">
          {changelog.releases.map((release) => (
            <div key={release.version} className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center gap-3 mb-4">
                <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-bold bg-red-100 text-red-800">
                  v{release.version}
                </span>
                <span className="text-sm text-gray-500">{release.date}</span>
                {release.version === changelog.current_version && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
                    Current
                  </span>
                )}
              </div>
              <ul className="space-y-2">
                {release.changes.map((change, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm text-gray-700">
                    <svg className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    {change}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
