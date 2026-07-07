import React from 'react';

/**
 * VersionBanner — Displays the APISIX version check status on the System Info page.
 *
 * Props:
 *   data — The version check response object from GET /api/system/version-check
 *     {
 *       running_version: string | null,
 *       latest_version: string | null,
 *       update_available: boolean,
 *       last_checked: string (ISO 8601),
 *       check_successful: boolean,
 *       error_message: string | null
 *     }
 *
 * States:
 *   1. Update available — amber alert with running/latest versions and last-checked date
 *   2. Up to date — green confirmation with current version and last-checked date
 *   3. Check failed (cached data exists) — warning with cached data and staleness indicator
 *   4. Unavailable (no prior data) — neutral message indicating version info is unavailable
 */

/**
 * Formats an ISO 8601 date string into a user-friendly format (e.g., "1 Jun 2026").
 */
function formatDate(isoString) {
  if (!isoString) return '—';
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return '—';
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${date.getDate()} ${months[date.getMonth()]} ${date.getFullYear()}`;
}

/**
 * Calculates how long ago a date was, returning a human-readable string.
 */
function timeAgo(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return '';
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffHours / 24);

  if (diffDays > 0) return `${diffDays} day${diffDays === 1 ? '' : 's'} ago`;
  if (diffHours > 0) return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`;
  return 'just now';
}

function VersionBanner({ data }) {
  // State 4: No data at all — unavailable
  if (!data) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
        <div className="flex items-start gap-3">
          <span className="text-xl" role="img" aria-label="info">ℹ️</span>
          <div>
            <h4 className="text-sm font-semibold text-gray-700">Version Information Unavailable</h4>
            <p className="mt-1 text-sm text-gray-500">
              No version check data is available. The check should be retried later.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const { running_version, latest_version, update_available, last_checked, check_successful, error_message } = data;

  // State 4 variant: check failed and no cached version data exists
  if (!check_successful && !running_version && !latest_version) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
        <div className="flex items-start gap-3">
          <span className="text-xl" role="img" aria-label="info">ℹ️</span>
          <div>
            <h4 className="text-sm font-semibold text-gray-700">Version Information Unavailable</h4>
            <p className="mt-1 text-sm text-gray-500">
              The version check could not be completed and no prior data exists. Please retry later.
            </p>
            {error_message && (
              <p className="mt-1 text-xs text-gray-400">Error: {error_message}</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  // State 3: Check failed but cached data exists — warning with staleness indicator
  if (!check_successful) {
    return (
      <div className="rounded-lg border border-orange-200 bg-orange-50 p-4">
        <div className="flex items-start gap-3">
          <span className="text-xl" role="img" aria-label="warning">⚠️</span>
          <div>
            <h4 className="text-sm font-semibold text-orange-800">Version Check Failed</h4>
            <p className="mt-1 text-sm text-orange-700">
              The latest version check could not be completed. Showing cached data.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-orange-700">
              {running_version && (
                <span>Running: <strong className="font-semibold">{running_version}</strong></span>
              )}
              {latest_version && (
                <span>Latest known: <strong className="font-semibold">{latest_version}</strong></span>
              )}
            </div>
            <p className="mt-2 text-xs text-orange-500">
              Last successful check: {formatDate(last_checked)} ({timeAgo(last_checked)})
            </p>
            {error_message && (
              <p className="mt-1 text-xs text-orange-400">Error: {error_message}</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  // State 1: Update available — amber alert
  if (update_available) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
        <div className="flex items-start gap-3">
          <span className="text-xl" role="img" aria-label="update available">🔔</span>
          <div>
            <h4 className="text-sm font-semibold text-amber-800">Update Available</h4>
            <p className="mt-1 text-sm text-amber-700">
              A newer version of APISIX is available. Consider planning an upgrade.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
              <span className="text-amber-700">
                Running: <strong className="font-semibold">{running_version || '—'}</strong>
              </span>
              <span className="text-amber-700">→</span>
              <span className="text-amber-700">
                Latest: <strong className="font-semibold">{latest_version || '—'}</strong>
              </span>
            </div>
            <p className="mt-2 text-xs text-amber-500">
              Checked: {formatDate(last_checked)}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // State 2: Up to date — green confirmation
  return (
    <div className="rounded-lg border border-green-200 bg-green-50 p-4">
      <div className="flex items-start gap-3">
        <span className="text-xl" role="img" aria-label="up to date">✅</span>
        <div>
          <h4 className="text-sm font-semibold text-green-800">Up to Date</h4>
          <p className="mt-1 text-sm text-green-700">
            APISIX is running the latest version.
          </p>
          <div className="mt-2 text-sm text-green-700">
            Version: <strong className="font-semibold">{running_version || '—'}</strong>
          </div>
          <p className="mt-2 text-xs text-green-500">
            Checked: {formatDate(last_checked)}
          </p>
        </div>
      </div>
    </div>
  );
}

export default VersionBanner;
