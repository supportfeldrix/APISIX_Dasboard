import { useState, useEffect, useRef, useCallback } from 'react';
import ResourceTable from '../components/ResourceTable';
import ResourceEditor from '../components/ResourceEditor';
import ConfirmDialog from '../components/ConfirmDialog';
import apiClient from '../api/client';
import { useAuthStore } from '../store/authStore';
import { parseEditorContent, stripReadOnlyFields } from '../utils/parseEditorContent';

/**
 * Consumers page — CRUD management for APISIX consumers.
 *
 * Fetches consumers from /apisix/consumers, displays them in a ResourceTable,
 * and provides create/edit/delete functionality via a slide-over editor panel.
 */

const COLUMNS = [
  { key: 'username', label: 'Username' },
  {
    key: 'plugins',
    label: 'Plugins',
    render: (item) => {
      const plugins = item.plugins || item.value?.plugins;
      const count = plugins ? Object.keys(plugins).length : 0;
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
          {count} {count === 1 ? 'plugin' : 'plugins'}
        </span>
      );
    },
  },
  {
    key: 'created_at',
    label: 'Created At',
    render: (item) => {
      const timestamp = item.created_at || item.create_time;
      if (!timestamp) return '—';
      const date = new Date(timestamp * 1000);
      return date.toLocaleDateString('en-GB', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    },
  },
];

export default function Consumers() {
  const role = useAuthStore((state) => state.role);

  const [consumers, setConsumers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Slide-over editor state
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const editorRef = useRef(null);

  // Confirm dialog state
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  /**
   * Fetch consumers list from APISIX Admin API via backend proxy.
   */
  const fetchConsumers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.get('/apisix/consumers');
      const list = response.data?.list || response.data?.node?.nodes || [];
      // Normalize the data — APISIX wraps items in { key, value } nodes
      const normalized = list.map((node) => {
        const item = node.value || node;
        return {
          ...item,
          username: item.username || node.key?.split('/').pop() || '—',
          created_at: item.create_time || item.created_at,
          id: item.username || node.key?.split('/').pop(),
        };
      });
      setConsumers(normalized);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to fetch consumers');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConsumers();
  }, [fetchConsumers]);

  /**
   * Open editor for creating a new consumer.
   */
  const handleCreate = () => {
    const template = {
      username: '',
      plugins: {},
    };
    setEditingItem(null);
    setEditorOpen(true);
    // Set initial content after a tick so the editor mounts first
    setTimeout(() => {
      if (editorRef.current) {
        editorRef.current.getValue();
      }
    }, 0);
    setEditingItem({ _isNew: true, _content: JSON.stringify(template, null, 2) });
  };

  /**
   * Open editor for editing an existing consumer.
   */
  const handleEdit = (item) => {
    // Build the payload to show in the editor
    const payload = {
      username: item.username,
      plugins: item.plugins || {},
      desc: item.desc || undefined,
      labels: item.labels || undefined,
    };
    // Remove undefined keys
    const cleaned = JSON.parse(JSON.stringify(payload));
    setEditingItem({ ...item, _content: JSON.stringify(cleaned, null, 2) });
    setEditorOpen(true);
  };

  /**
   * Submit consumer create/update.
   * PUT to /apisix/consumers/{username}
   */
  const handleSubmit = async () => {
    if (!editorRef.current) return;
    if (!editorRef.current.isValid()) return;

    const content = editorRef.current.getValue();
    const { data: parsed, error: parseError } = parseEditorContent(content);
    if (parseError || !parsed) {
      setError(parseError || 'Failed to parse editor content.');
      return;
    }

    // Remove read-only fields before sending to APISIX
    const payload = stripReadOnlyFields(parsed);

    // Determine the username for the URL
    const username = parsed.username || editingItem?.username;
    if (!username) {
      setError('Username is required for consumer creation.');
      return;
    }

    setSubmitting(true);
    try {
      await apiClient.put(`/apisix/consumers/${username}`, payload);
      setEditorOpen(false);
      setEditingItem(null);
      await fetchConsumers();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to save consumer');
    } finally {
      setSubmitting(false);
    }
  };

  /**
   * Cancel editing — close the slide-over.
   */
  const handleCancel = () => {
    setEditorOpen(false);
    setEditingItem(null);
  };

  /**
   * Open delete confirmation dialog.
   */
  const handleDeleteClick = (item) => {
    setDeleteTarget(item);
  };

  /**
   * Confirm deletion of a consumer.
   */
  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await apiClient.delete(`/apisix/consumers/${deleteTarget.username}`);
      setDeleteTarget(null);
      await fetchConsumers();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to delete consumer');
    } finally {
      setDeleting(false);
    }
  };

  /**
   * Cancel deletion.
   */
  const handleDeleteCancel = () => {
    setDeleteTarget(null);
  };

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Consumers</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage APISIX consumers and their plugin configurations.
          </p>
        </div>
        {role === 'admin' && (
          <button
            onClick={handleCreate}
            className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Create Consumer
          </button>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-4">
          <div className="flex">
            <svg className="h-5 w-5 text-red-400 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                clipRule="evenodd"
              />
            </svg>
            <div className="ml-3 flex-1">
              <p className="text-sm text-red-700">{error}</p>
            </div>
            <button
              onClick={() => setError(null)}
              className="ml-3 text-red-400 hover:text-red-600"
              aria-label="Dismiss error"
            >
              <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path
                  fillRule="evenodd"
                  d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                  clipRule="evenodd"
                />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* Consumers table */}
      <ResourceTable
        columns={COLUMNS}
        data={consumers}
        loading={loading}
        role={role}
        onEdit={handleEdit}
        onDelete={handleDeleteClick}
      />

      {/* Slide-over editor panel */}
      {editorOpen && (
        <div className="fixed inset-0 z-40 overflow-hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black bg-opacity-30 transition-opacity"
            onClick={handleCancel}
            aria-hidden="true"
          />

          {/* Slide-over panel */}
          <div className="absolute inset-y-0 right-0 flex max-w-full pl-10">
            <div className="w-screen max-w-2xl">
              <div className="flex h-full flex-col bg-white shadow-xl">
                {/* Panel header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-gray-50">
                  <h2 className="text-lg font-semibold text-gray-900">
                    {editingItem?._isNew ? 'Create Consumer' : `Edit Consumer: ${editingItem?.username || ''}`}
                  </h2>
                  <button
                    onClick={handleCancel}
                    className="rounded-md text-gray-400 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    aria-label="Close panel"
                  >
                    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                {/* Editor content */}
                <div className="flex-1 overflow-y-auto p-6">
                  <ResourceEditor
                    ref={editorRef}
                    value={editingItem?._content || ''}
                    onSubmit={handleSubmit}
                    onCancel={handleCancel}
                    readOnly={role !== 'admin'}
                  />
                </div>

                {/* Panel footer */}
                <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 bg-gray-50">
                  <button
                    onClick={handleCancel}
                    className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2 transition-colors"
                  >
                    Cancel
                  </button>
                  {role === 'admin' && (
                    <button
                      onClick={handleSubmit}
                      disabled={submitting}
                      className="inline-flex items-center rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
                    >
                      {submitting ? (
                        <>
                          <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                          </svg>
                          Saving...
                        </>
                      ) : (
                        'Save Consumer'
                      )}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete Consumer"
        message={`Are you sure you want to delete consumer "${deleteTarget?.username || ''}"? This action cannot be undone.`}
        confirmLabel={deleting ? 'Deleting...' : 'Delete'}
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
      />
    </div>
  );
}
