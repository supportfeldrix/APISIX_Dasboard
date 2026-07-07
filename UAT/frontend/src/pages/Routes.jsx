import { useState, useEffect, useRef } from 'react';
import ResourceTable from '../components/ResourceTable';
import ResourceEditor from '../components/ResourceEditor';
import ConfirmDialog from '../components/ConfirmDialog';
import apiClient from '../api/client';
import { useAuthStore } from '../store/authStore';
import { parseEditorContent, stripReadOnlyFields } from '../utils/parseEditorContent';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'uri', label: 'URI' },
  {
    key: 'methods',
    label: 'Methods',
    render: (item) =>
      Array.isArray(item.methods) ? item.methods.join(', ') : item.methods || '—',
  },
  {
    key: 'status',
    label: 'Status',
    render: (item) => (
      <span
        className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
          item.status === 1
            ? 'bg-green-100 text-green-800'
            : 'bg-gray-100 text-gray-800'
        }`}
      >
        {item.status === 1 ? 'Enabled' : 'Disabled'}
      </span>
    ),
  },
  { key: 'upstream_id', label: 'Upstream ID' },
];

export default function Routes() {
  const role = useAuthStore((state) => state.role);

  const [routes, setRoutes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [selectedItem, setSelectedItem] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const editorRef = useRef(null);

  // Fetch routes on mount
  useEffect(() => {
    fetchRoutes();
  }, []);

  async function fetchRoutes() {
    setLoading(true);
    try {
      const response = await apiClient.get('/apisix/routes');
      const list = response.data?.list || response.data?.rows || response.data || [];
      // Normalize: APISIX wraps each item in a `value` key
      const normalized = list.map((entry) => entry.value || entry);
      setRoutes(normalized);
    } catch (error) {
      console.error('Failed to fetch routes:', error);
      setRoutes([]);
    } finally {
      setLoading(false);
    }
  }

  // Open editor for creating a new route
  function handleCreate() {
    setSelectedItem(null);
    setEditorOpen(true);
  }

  // Open editor pre-filled with existing route JSON
  function handleEdit(item) {
    setSelectedItem(item);
    setEditorOpen(true);
  }

  // Close the editor panel
  function handleEditorCancel() {
    setEditorOpen(false);
    setSelectedItem(null);
  }

  // Submit from editor: PUT (update) or POST (create)
  async function handleEditorSubmit() {
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

    try {
      if (selectedItem && selectedItem.id) {
        // Update existing route
        await apiClient.put(`/apisix/routes/${selectedItem.id}`, payload);
      } else {
        // Create new route
        await apiClient.post('/apisix/routes', payload);
      }
      setEditorOpen(false);
      setSelectedItem(null);
      await fetchRoutes();
    } catch (error) {
      console.error('Failed to save route:', error);
    }
  }

  // Toggle route status (enable/disable) — admin only
  async function handleToggle(item) {
    if (role !== 'admin') return;

    const newStatus = item.status === 1 ? 0 : 1;
    try {
      await apiClient.patch(`/apisix/routes/${item.id}`, { status: newStatus });
      await fetchRoutes();
    } catch (error) {
      console.error('Failed to toggle route status:', error);
    }
  }

  // Open delete confirmation dialog — admin only
  function handleDelete(item) {
    setDeleteTarget(item);
  }

  // Confirm deletion
  async function handleDeleteConfirm() {
    if (!deleteTarget) return;
    try {
      await apiClient.delete(`/apisix/routes/${deleteTarget.id}`);
      setDeleteTarget(null);
      await fetchRoutes();
    } catch (error) {
      console.error('Failed to delete route:', error);
    }
  }

  // Cancel deletion
  function handleDeleteCancel() {
    setDeleteTarget(null);
  }

  return (
    <div className="space-y-4">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Routes</h1>
        {role === 'admin' && (
          <button
            onClick={handleCreate}
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
          >
            <svg
              className="w-4 h-4 mr-1.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Create Route
          </button>
        )}
      </div>

      {/* Routes table */}
      <ResourceTable
        columns={COLUMNS}
        data={routes}
        loading={loading}
        role={role}
        onEdit={handleEdit}
        onDelete={handleDelete}
        onToggle={role === 'admin' ? handleToggle : undefined}
      />

      {/* Slide-over editor panel */}
      {editorOpen && (
        <div className="fixed inset-0 z-40 overflow-hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black bg-opacity-50 transition-opacity"
            onClick={handleEditorCancel}
            aria-hidden="true"
          />

          {/* Slide-over panel from right */}
          <div className="absolute inset-y-0 right-0 flex max-w-full pl-10">
            <div className="w-screen max-w-2xl">
              <div className="flex h-full flex-col bg-white shadow-xl">
                {/* Panel header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                  <h2 className="text-lg font-semibold text-gray-900">
                    {selectedItem ? 'Edit Route' : 'Create Route'}
                  </h2>
                  <button
                    onClick={handleEditorCancel}
                    className="rounded-md text-gray-400 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    aria-label="Close panel"
                  >
                    <svg
                      className="h-6 w-6"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                </div>

                {/* Editor body */}
                <div className="flex-1 overflow-hidden p-4">
                  <ResourceEditor
                    ref={editorRef}
                    value={
                      selectedItem
                        ? JSON.stringify(selectedItem, null, 2)
                        : JSON.stringify(
                            {
                              name: '',
                              uri: '/*',
                              methods: ['GET'],
                              upstream_id: '',
                              status: 1,
                            },
                            null,
                            2
                          )
                    }
                    onSubmit={handleEditorSubmit}
                    onCancel={handleEditorCancel}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete Route"
        message={`Are you sure you want to delete route "${deleteTarget?.name || deleteTarget?.id || ''}"? This action cannot be undone.`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
        variant="danger"
      />
    </div>
  );
}
