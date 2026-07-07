import React, { useState, useEffect, useRef, useCallback } from 'react';
import ResourceTable from '../components/ResourceTable';
import ResourceEditor from '../components/ResourceEditor';
import ConfirmDialog from '../components/ConfirmDialog';
import apiClient from '../api/client';
import { useAuthStore } from '../store/authStore';
import { parseEditorContent, stripReadOnlyFields } from '../utils/parseEditorContent';

/**
 * Upstreams page — CRUD management for APISIX upstreams.
 *
 * Displays a table of upstreams with columns: id, name, type (load-balancing algorithm), node count.
 * Provides create/edit/delete functionality via a slide-over panel and confirmation dialog.
 */

const UPSTREAM_TEMPLATE = {
  name: '',
  type: 'roundrobin',
  nodes: {
    'httpbin.org:80': 1,
  },
};

const columns = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name', render: (item) => item.name || '—' },
  {
    key: 'type',
    label: 'Type',
    render: (item) => (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
        {item.type || 'roundrobin'}
      </span>
    ),
  },
  {
    key: 'nodes',
    label: 'Node Count',
    render: (item) => {
      if (!item.nodes) return '0';
      if (Array.isArray(item.nodes)) return String(item.nodes.length);
      if (typeof item.nodes === 'object') return String(Object.keys(item.nodes).length);
      return '0';
    },
  },
];

export default function Upstreams() {
  const role = useAuthStore((state) => state.role);
  const editorRef = useRef(null);

  const [upstreams, setUpstreams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Slide-over panel state
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [editorValue, setEditorValue] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Confirm dialog state
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  // Fetch upstreams list
  const fetchUpstreams = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.get('/apisix/upstreams');
      const list = response.data?.list || response.data?.data?.rows || [];
      // Normalize: APISIX wraps each item in { key, value, ... }
      const normalized = list.map((entry) => {
        const item = entry.value || entry;
        return {
          ...item,
          id: item.id || entry.key?.replace('/apisix/upstreams/', ''),
        };
      });
      setUpstreams(normalized);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch upstreams');
      setUpstreams([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUpstreams();
  }, [fetchUpstreams]);

  // Open editor for creating a new upstream
  const handleCreate = () => {
    setEditingItem(null);
    setEditorValue(JSON.stringify(UPSTREAM_TEMPLATE, null, 2));
    setEditorOpen(true);
  };

  // Open editor for editing an existing upstream
  const handleEdit = (item) => {
    setEditingItem(item);
    // Strip internal fields for editing
    const { id, create_time, update_time, ...editable } = item;
    setEditorValue(JSON.stringify(editable, null, 2));
    setEditorOpen(true);
  };

  // Close editor panel
  const handleCancel = () => {
    setEditorOpen(false);
    setEditingItem(null);
    setEditorValue('');
  };

  // Submit create or update
  const handleSubmit = async () => {
    if (editorRef.current && !editorRef.current.isValid()) {
      return;
    }

    setSubmitting(true);
    try {
      const content = editorRef.current ? editorRef.current.getValue() : editorValue;
      const { data: parsed, error: parseError } = parseEditorContent(content);
      if (parseError || !parsed) {
        setError(parseError || 'Failed to parse editor content');
        setSubmitting(false);
        return;
      }

      // Remove read-only fields before sending to APISIX
      const payload = stripReadOnlyFields(parsed);

      if (editingItem) {
        // Update existing upstream
        await apiClient.put(`/apisix/upstreams/${editingItem.id}`, payload);
      } else {
        // Create new upstream
        await apiClient.post('/apisix/upstreams', payload);
      }

      handleCancel();
      await fetchUpstreams();
    } catch (err) {
      console.error('Submit error:', err);
      setError(err.response?.data?.detail || 'Failed to save upstream');
    } finally {
      setSubmitting(false);
    }
  };

  // Delete upstream
  const handleDeleteClick = (item) => {
    setDeleteTarget(item);
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;

    setDeleting(true);
    try {
      await apiClient.delete(`/apisix/upstreams/${deleteTarget.id}`);
      setDeleteTarget(null);
      await fetchUpstreams();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to delete upstream');
    } finally {
      setDeleting(false);
    }
  };

  const handleDeleteCancel = () => {
    setDeleteTarget(null);
  };

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Upstreams</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage upstream targets and load-balancing configurations.
          </p>
        </div>
        {role === 'admin' && (
          <button
            onClick={handleCreate}
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
          >
            <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Create Upstream
          </button>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="rounded-md bg-red-50 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <p className="text-sm text-red-700">{error}</p>
            </div>
            <div className="ml-auto pl-3">
              <button
                onClick={() => setError(null)}
                className="inline-flex rounded-md bg-red-50 p-1.5 text-red-500 hover:bg-red-100 focus:outline-none"
                aria-label="Dismiss error"
              >
                <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Upstreams table */}
      <ResourceTable
        columns={columns}
        data={upstreams}
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
            className="absolute inset-0 bg-black bg-opacity-50 transition-opacity"
            onClick={handleCancel}
            aria-hidden="true"
          />

          {/* Slide-over panel */}
          <div className="absolute inset-y-0 right-0 flex max-w-full pl-10">
            <div className="w-screen max-w-2xl">
              <div className="flex h-full flex-col bg-white shadow-xl">
                {/* Panel header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                  <h2 className="text-lg font-semibold text-gray-900">
                    {editingItem ? `Edit Upstream: ${editingItem.name || editingItem.id}` : 'Create Upstream'}
                  </h2>
                  <button
                    onClick={handleCancel}
                    className="rounded-md text-gray-400 hover:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    aria-label="Close panel"
                  >
                    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                {/* Editor content */}
                <div className="flex-1 overflow-y-auto px-6 py-4">
                  <ResourceEditor
                    ref={editorRef}
                    value={editorValue}
                    onSubmit={handleSubmit}
                    onCancel={handleCancel}
                    readOnly={role !== 'admin'}
                  />
                </div>

                {/* Panel footer */}
                <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200">
                  <button
                    onClick={handleCancel}
                    className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2"
                  >
                    Cancel
                  </button>
                  {role === 'admin' && (
                    <button
                      onClick={handleSubmit}
                      disabled={submitting}
                      className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
                    >
                      {submitting ? 'Saving...' : editingItem ? 'Update' : 'Create'}
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
        title="Delete Upstream"
        message={`Are you sure you want to delete upstream "${deleteTarget?.name || deleteTarget?.id}"? This action cannot be undone.`}
        confirmLabel={deleting ? 'Deleting...' : 'Delete'}
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
      />
    </div>
  );
}
