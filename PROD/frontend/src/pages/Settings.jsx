import { useState, useEffect } from 'react';
import apiClient from '../api/client';
import { useAuthStore } from '../store/authStore';
import ConfirmDialog from '../components/ConfirmDialog';

export default function Settings() {
  const role = useAuthStore((state) => state.role);
  const currentUsername = useAuthStore((state) => state.user);

  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Create user form
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState('viewer');
  const [creating, setCreating] = useState(false);

  // Confirm dialog
  const [confirmAction, setConfirmAction] = useState(null);

  // Delete user state
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  // ControlM Escalation settings
  const [controlmEnabled, setControlmEnabled] = useState(false);
  const [landingZone, setLandingZone] = useState('');
  const [gracePeriod, setGracePeriod] = useState(0);
  const [controlmLoading, setControlmLoading] = useState(true);
  const [controlmSaving, setControlmSaving] = useState(false);

  useEffect(() => {
    fetchUsers();
    fetchControlmSettings();
  }, []);

  async function fetchUsers() {
    setLoading(true);
    setError('');
    try {
      const response = await apiClient.get('/users');
      setUsers(response.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch users');
    } finally {
      setLoading(false);
    }
  }

  async function handleRoleChange(username, newRole) {
    setError('');
    setSuccess('');
    try {
      await apiClient.put(`/users/${username}/role`, { role: newRole });
      setSuccess(`User "${username}" role updated to "${newRole}"`);
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to update role');
    }
  }

  async function handleToggleActive(username) {
    setError('');
    setSuccess('');
    try {
      const response = await apiClient.put(`/users/${username}/active`);
      setSuccess(response.data.message);
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to toggle user status');
    }
  }

  async function handleCreateUser(e) {
    e.preventDefault();
    setError('');
    setSuccess('');
    setCreating(true);
    try {
      await apiClient.post('/users', {
        username: newUsername,
        password: newPassword,
        role: newRole,
      });
      setSuccess(`User "${newUsername}" created successfully`);
      setNewUsername('');
      setNewPassword('');
      setNewRole('viewer');
      setShowCreateForm(false);
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create user');
    } finally {
      setCreating(false);
    }
  }

  async function handleDeleteUser(username) {
    setDeleting(true);
    setError('');
    setSuccess('');
    try {
      await apiClient.delete(`/users/${username}`, { timeout: 30000 });
      setSuccess(`User '${username}' deleted successfully`);
      setTimeout(() => setSuccess(''), 5000);
      fetchUsers();
    } catch (err) {
      if (err.code === 'ECONNABORTED') {
        setError('Request timed out. Please try again.');
      } else {
        setError(err.response?.data?.detail || 'Failed to delete user');
      }
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  }

  async function fetchControlmSettings() {
    setControlmLoading(true);
    try {
      const response = await apiClient.get('/escalation/settings');
      const data = response.data;
      setControlmEnabled(data.controlm_enabled ?? false);
      setLandingZone(data.landing_zone ?? '');
      setGracePeriod(data.grace_period ?? 0);
    } catch (err) {
      // If endpoint doesn't exist yet or fails, leave defaults
      console.error('Failed to load ControlM settings:', err);
    } finally {
      setControlmLoading(false);
    }
  }

  async function handleSaveControlmSettings(e) {
    e.preventDefault();
    setError('');
    setSuccess('');

    // Client-side validation
    if (!landingZone || landingZone.length === 0 || landingZone.length > 500) {
      setError('Landing Zone path must be between 1 and 500 characters.');
      return;
    }
    const gracePeriodInt = parseInt(gracePeriod, 10);
    if (isNaN(gracePeriodInt) || gracePeriodInt < 0 || gracePeriodInt > 86400) {
      setError('Grace Period must be an integer between 0 and 86400 seconds.');
      return;
    }

    setControlmSaving(true);
    try {
      await apiClient.put('/escalation/settings', {
        controlm_enabled: controlmEnabled,
        landing_zone: landingZone,
        grace_period: gracePeriodInt,
      });
      setSuccess('ControlM Escalation settings saved successfully.');
      setTimeout(() => setSuccess(''), 5000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save ControlM Escalation settings.');
    } finally {
      setControlmSaving(false);
    }
  }

  if (role !== 'admin') {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 text-center">
          <svg className="w-12 h-12 text-yellow-400 mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <h3 className="text-lg font-medium text-yellow-800">Viewer Access</h3>
          <p className="text-sm text-yellow-700 mt-2">
            You are logged in as a <strong>viewer</strong>. Only admins can manage user roles and settings.
            Contact your administrator to request elevated access.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage user accounts and roles. LDAP users will appear here after their first login.
          </p>
        </div>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-red-700 rounded-md hover:bg-red-800 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 transition-colors"
        >
          <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Create User
        </button>
      </div>

      {/* Messages */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md text-sm flex items-center justify-between" role="alert">
          <span>{error}</span>
          <button
            onClick={() => setError('')}
            className="ml-3 text-red-500 hover:text-red-700 focus:outline-none"
            aria-label="Dismiss error"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}
      {success && (
        <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-md text-sm" role="status">
          {success}
        </div>
      )}

      {/* Create User Form */}
      {showCreateForm && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Create New User</h3>
          <form onSubmit={handleCreateUser} className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
            <div>
              <label className="block text-xs font-semibold text-gray-600 uppercase mb-1">Username</label>
              <input
                type="text"
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value)}
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-red-500 focus:border-red-500"
                placeholder="username"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 uppercase mb-1">Password</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-red-500 focus:border-red-500"
                placeholder="password"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 uppercase mb-1">Role</label>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-red-500 focus:border-red-500"
              >
                <option value="viewer">Viewer</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={creating}
                className="px-4 py-2 text-sm font-medium text-white bg-red-700 rounded-md hover:bg-red-800 disabled:opacity-50 transition-colors"
              >
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button
                type="button"
                onClick={() => setShowCreateForm(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Info box about LDAP */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex items-start gap-3">
          <svg className="w-5 h-5 text-blue-500 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div className="text-sm text-blue-700">
            <p className="font-medium">LDAP Integration Note</p>
            <p className="mt-1">
              When LDAP is configured, users who log in via LDAP will automatically be created with the <strong>viewer</strong> role.
              Admins can promote them to <strong>admin</strong> from this page to allow route/service modifications.
            </p>
          </div>
        </div>
      </div>

      {/* Users Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Username</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Current Role</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {loading ? (
                <tr>
                  <td colSpan={4} className="px-6 py-8 text-center text-gray-500">Loading users...</td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-6 py-8 text-center text-gray-500">No users found</td>
                </tr>
              ) : (
                users.map((user) => (
                  <tr key={user.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 text-sm font-medium text-gray-900">
                      {user.username}
                      {user.username === currentUsername && (
                        <span className="ml-2 text-xs text-gray-400">(you)</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        user.role === 'admin'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}>
                        {user.role}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        user.is_active
                          ? 'bg-green-100 text-green-800'
                          : 'bg-red-100 text-red-800'
                      }`}>
                        {user.is_active ? 'Active' : 'Disabled'}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <div className="flex items-center gap-2">
                        {/* Role toggle */}
                        {user.username !== currentUsername && (
                          <button
                            onClick={() => handleRoleChange(
                              user.username,
                              user.role === 'admin' ? 'viewer' : 'admin'
                            )}
                            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                              user.role === 'viewer'
                                ? 'bg-red-50 text-red-700 hover:bg-red-100'
                                : 'bg-gray-50 text-gray-700 hover:bg-gray-100'
                            }`}
                          >
                            {user.role === 'viewer' ? 'Promote to Admin' : 'Demote to Viewer'}
                          </button>
                        )}

                        {/* Active toggle */}
                        {user.username !== currentUsername && (
                          <button
                            onClick={() => handleToggleActive(user.username)}
                            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                              user.is_active
                                ? 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100'
                                : 'bg-green-50 text-green-700 hover:bg-green-100'
                            }`}
                          >
                            {user.is_active ? 'Disable' : 'Enable'}
                          </button>
                        )}

                        {/* Delete button */}
                        {user.username !== currentUsername && (
                          <button
                            onClick={() => setDeleteTarget(user.username)}
                            className="px-3 py-1.5 text-xs font-medium rounded-md bg-red-50 text-red-700 hover:bg-red-100 transition-colors"
                          >
                            Delete
                          </button>
                        )}

                        {user.username === currentUsername && (
                          <span className="text-xs text-gray-400 italic">Cannot modify own account</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Delete User Confirm Dialog */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete User"
        message={`Are you sure you want to permanently delete user '${deleteTarget}'? This action cannot be undone.`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={() => handleDeleteUser(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
        disabled={deleting}
      />

      {/* ControlM Escalation Settings */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-gray-800">ControlM Escalation</h3>
          <p className="text-sm text-gray-500 mt-1">
            Configure phone-call escalation via ControlM when alerts go unacknowledged.
          </p>
        </div>

        {controlmLoading ? (
          <p className="text-sm text-gray-500">Loading escalation settings...</p>
        ) : (
          <form onSubmit={handleSaveControlmSettings} className="space-y-4">
            {/* Global Enable Toggle */}
            <div className="flex items-center gap-3">
              <label htmlFor="controlm-enabled" className="relative inline-flex items-center cursor-pointer">
                <input
                  id="controlm-enabled"
                  type="checkbox"
                  checked={controlmEnabled}
                  onChange={(e) => setControlmEnabled(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-red-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-red-700"></div>
              </label>
              <span className="text-sm font-medium text-gray-700">Global Enable</span>
            </div>

            {/* Landing Zone Path */}
            <div>
              <label htmlFor="landing-zone" className="block text-xs font-semibold text-gray-600 uppercase mb-1">
                Landing Zone Path
              </label>
              <input
                id="landing-zone"
                type="text"
                value={landingZone}
                onChange={(e) => setLandingZone(e.target.value)}
                placeholder="/mnt/landing_zone/mft/prod/incoming/croit/escalation/"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-red-500 focus:border-red-500"
                maxLength={500}
              />
              <p className="text-xs text-gray-400 mt-1">Network share path where trigger files are written (1-500 characters).</p>
            </div>

            {/* Grace Period */}
            <div>
              <label htmlFor="grace-period" className="block text-xs font-semibold text-gray-600 uppercase mb-1">
                Grace Period (seconds)
              </label>
              <input
                id="grace-period"
                type="number"
                value={gracePeriod}
                onChange={(e) => setGracePeriod(e.target.value)}
                min={0}
                max={86400}
                className="w-full md:w-48 px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-red-500 focus:border-red-500"
              />
              <p className="text-xs text-gray-400 mt-1">Time in seconds before escalation (0 = immediate). Max 86400 (24 hours).</p>
            </div>

            {/* Save Button */}
            <div className="pt-2">
              <button
                type="submit"
                disabled={controlmSaving}
                className="px-4 py-2 text-sm font-medium text-white bg-red-700 rounded-md hover:bg-red-800 disabled:opacity-50 transition-colors"
              >
                {controlmSaving ? 'Saving...' : 'Save Settings'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
