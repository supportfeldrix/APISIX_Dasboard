import React, { useState, useEffect, useCallback, useRef } from 'react';
import ResourceTable from '../components/ResourceTable';
import ResourceEditor from '../components/ResourceEditor';
import ConfirmDialog from '../components/ConfirmDialog';
import apiClient from '../api/client';
import { useAuthStore } from '../store/authStore';
import { parseEditorContent, stripReadOnlyFields } from '../utils/parseEditorContent';

/**
 * Services page — CRUD management for APISIX services.
 *
 * Displays a table of services with columns: id, name, upstream_id, plugin count.
 * Supports create, edit, and delete operations via a slide-over editor panel.
 */
export default function Services() {
  const role = useAuthStore((state) => state.role);

  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Editor slide-over state
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingService, setEditingService] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const editorRef = useRef(null);

  // Confirm dialog state
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  // Fetch services list
  const fetchServices = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.get('/apisix/services');
      const data = response.data;
      // APISIX Admin API returns { list: [...] } or { node: { nodes: [...] } }
      let items = [];
      if (data?.list) {
        items = data.list.map((item) => item.value || item);
      } else if (data?.node?.nodes) {
        items = data.node.nodes.map((node) => node.value || node);
      } else if (Array.isArray(data)) {
        items = data;
      }
      setServices(items);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch services');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchServices();
  }, [fetchServices]);

  // Table columns
  const columns = [
    { key: 'id', label: 'ID' },
    { key: 'name', label: 'Name' },
    { key: 'upstream_id', label: 'Upstream ID' },
    {
      key: 'plugins',
      label: 'Plugins',
      render: (item) => {
        const count = item.plugins ? Object.keys(item.plugins).length : 0;
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
            {count}
          </span>
        );
      },
    },
  ];

  // Open editor for creating a new service
  const handleCreate = () => {
    setEditingService(null);
    setEditorOpen(true);
  };

  // Open editor for editing an existing service
  const handleEdit = (item) => {
    setEditingService(item);
    setEditorOpen(true);
  };

  // Close editor
  const handleEditorCancel = () => {
    setEditorOpen(false);
    setEditingService(null);
  };

  // Submit create or update
  const handleEditorSubmit = async () => {
    if (!editorRef.current) return;
    if (!editorRef.current.isValid()) return;

    const content = editorRef.current.getValue();
    const { data: parsed, error: parseError } = parseEditorContent(content);
    if (parseError || !parsed) {
      console.error('Editor parse error:', parseError);
      return;
    }

    // Remove read-only fields before sending to APISIX
    const payload = stripReadOnlyFields(parsed);

    setSubmitting(true);
    try {
      if (editingService) {
        // Update existing service
        await apiClient.put(`/apisix/services/${editingService.id}`, payload);
      } else {
        // Create new service — use POST if no id, PUT if id is provided
        if (parsed.id) {
          await apiClient.put(`/apisix/services/${parsed.id}`, payload);
        } else {
          await apiClient.post('/apisix/services', payload);
        }
      }
      setEditorOpen(false);
      setEditingService(null);
      await fetchServices();
    } catch (err) {
      console.error('Failed to save service:', err.response?.data || err.message);
    } finally {
      setSubmitting(false);
    }
  };

  // Delete service
  const handleDelete = (item) => {
    setDeleteTarget(item);
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await apiClient.delete(`/apisix/services/${deleteTarget.id}`);
      setDeleteTarget(null);
      await fetchServices();
    } catch (err) {
      console.error('Failed to delete service:', err.response?.data || err.message);
    } finally {
      setDeleting(false);
    }
  };

  const handleDeleteCancel = () => {
    setDeleteTarget(null);
  };

  // Prepare editor initial value
  const getEditorValue = () => {
    if (editingService) {
      return JSON.stringify(editingService, null, 2);
    }
    // Template for new service
    return JSON.stringify(
      {
        name: '',
        upstream_id: '',
        plugins: {},
      },
      null,
      2
    );
  };

  return (
    <div className="p-6 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Services</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage APISIX services configuration
          </p>
        </div>
        <button
          onClick={handleCreate}
          className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
        >
          <svg
            className="w-4 h-4 mr-2"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Create Service
        </button>
      </div>

      {/* Error message */}
      {error && (
        <div className="rounded-md bg-red-50 p-4">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Services table */}
      <ResourceTable
        columns={columns}
        data={services}
        loading={loading}
        role={role}
        onEdit={handleEdit}
        onDelete={handleDelete}
      />

      {/* Slide-over editor panel */}
      {editorOpen && (
        <div className="fixed inset-0 z-40 flex justify-end">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black bg-opacity-30 transition-opacity"
            onClick={handleEditorCancel}
            aria-hidden="true"
          />

          {/* Slide-over panel */}
          <div className="relative z-50 w-full max-w-2xl bg-white shadow-xl flex flex-col">
            {/* Panel header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold text-gray-900">
                {editingService ? 'Edit Service' : 'Create Service'}
              </h2>
              <button
                onClick={handleEditorCancel}
                className="text-gray-400 hover:text-gray-600 transition-colors"
                aria-label="Close editor"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Editor content */}
            <div className="flex-1 overflow-y-auto p-6">
              <ResourceEditor
                ref={editorRef}
                value={getEditorValue()}
                onSubmit={handleEditorSubmit}
                onCancel={handleEditorCancel}
                readOnly={submitting}
              />
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete Service"
        message={`Are you sure you want to delete service "${deleteTarget?.name || deleteTarget?.id || ''}"? This action cannot be undone.`}
        confirmLabel={deleting ? 'Deleting...' : 'Delete'}
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
      />
    </div>
  );
}
