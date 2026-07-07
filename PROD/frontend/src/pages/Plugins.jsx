import { useState, useEffect, useRef, useCallback } from 'react';
import ResourceEditor from '../components/ResourceEditor';
import apiClient from '../api/client';
import { useAuthStore } from '../store/authStore';
import { parseEditorContent, stripReadOnlyFields } from '../utils/parseEditorContent';

export default function Plugins() {
  const [globalRules, setGlobalRules] = useState([]);
  const [pluginMetadata, setPluginMetadata] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Slide-over state
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [editingType, setEditingType] = useState(''); // 'global_rules' or 'plugin_metadata'
  const [submitting, setSubmitting] = useState(false);

  const editorRef = useRef(null);
  const role = useAuthStore((state) => state.role);
  const isAdmin = role === 'admin';

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [rulesRes, metadataRes] = await Promise.all([
        apiClient.get('/apisix/global_rules'),
        apiClient.get('/apisix/plugin_metadata'),
      ]);

      const rules = rulesRes.data?.list || rulesRes.data?.node?.nodes || rulesRes.data || [];
      const metadata = metadataRes.data?.list || metadataRes.data?.node?.nodes || metadataRes.data || [];

      setGlobalRules(Array.isArray(rules) ? rules : []);
      setPluginMetadata(Array.isArray(metadata) ? metadata : []);
    } catch (err) {
      setError('Failed to load plugin data. Please try again.');
      console.error('Plugins fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleEdit = (item, type) => {
    setEditingItem(item);
    setEditingType(type);
    setEditorOpen(true);
  };

  const handleCloseEditor = () => {
    setEditorOpen(false);
    setEditingItem(null);
    setEditingType('');
  };

  const handleSubmit = async () => {
    if (!editorRef.current) return;

    if (!editorRef.current.isValid()) {
      return;
    }

    const content = editorRef.current.getValue();
    const { data: parsed, error: parseError } = parseEditorContent(content);
    if (parseError || !parsed) {
      setError(parseError || 'Failed to parse editor content.');
      return;
    }

    // Remove read-only fields before sending to APISIX
    const payload = stripReadOnlyFields(parsed);

    const id = editingItem?.id || editingItem?.key || editingItem?.value?.id;
    if (!id) {
      setError('Cannot determine item ID for update.');
      return;
    }

    setSubmitting(true);
    try {
      await apiClient.put(`/apisix/${editingType}/${id}`, payload);
      handleCloseEditor();
      await fetchData();
    } catch (err) {
      const detail = err.response?.data?.detail || err.message;
      setError(`Failed to update: ${detail}`);
    } finally {
      setSubmitting(false);
    }
  };

  const getItemDisplay = (item) => {
    const id = item?.id || item?.key || item?.value?.id || 'unknown';
    const plugins = item?.plugins || item?.value?.plugins || {};
    const pluginNames = Object.keys(plugins);
    return { id, pluginNames };
  };

  const getEditorValue = (item) => {
    const value = item?.value || item;
    return JSON.stringify(value, null, 2);
  };

  if (loading) {
    return (
      <div className="p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-gray-200 rounded w-1/4"></div>
          <div className="h-32 bg-gray-200 rounded"></div>
          <div className="h-8 bg-gray-200 rounded w-1/4"></div>
          <div className="h-32 bg-gray-200 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-8">
      <h1 className="text-2xl font-bold text-gray-800">Plugins</h1>

      {error && (
        <div
          className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* Global Rules Section */}
      <section>
        <h2 className="text-lg font-semibold text-gray-700 mb-4 border-b border-gray-200 pb-2">
          Global Rules
        </h2>
        {globalRules.length === 0 ? (
          <p className="text-gray-500 text-sm">No global rules configured.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 border border-gray-200 rounded-lg">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Plugins
                  </th>
                  {isAdmin && (
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Actions
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {globalRules.map((rule, index) => {
                  const { id, pluginNames } = getItemDisplay(rule);
                  return (
                    <tr key={id || index} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm font-mono text-gray-900">
                        {id}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {pluginNames.length > 0
                          ? pluginNames.join(', ')
                          : 'None'}
                      </td>
                      {isAdmin && (
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => handleEdit(rule, 'global_rules')}
                            className="inline-flex items-center px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-50 text-indigo-700 hover:bg-indigo-100 transition-colors"
                          >
                            Edit
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Plugin Metadata Section */}
      <section>
        <h2 className="text-lg font-semibold text-gray-700 mb-4 border-b border-gray-200 pb-2">
          Plugin Metadata
        </h2>
        {pluginMetadata.length === 0 ? (
          <p className="text-gray-500 text-sm">No plugin metadata configured.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 border border-gray-200 rounded-lg">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Plugins
                  </th>
                  {isAdmin && (
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Actions
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {pluginMetadata.map((meta, index) => {
                  const { id, pluginNames } = getItemDisplay(meta);
                  return (
                    <tr key={id || index} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm font-mono text-gray-900">
                        {id}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {pluginNames.length > 0
                          ? pluginNames.join(', ')
                          : 'None'}
                      </td>
                      {isAdmin && (
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => handleEdit(meta, 'plugin_metadata')}
                            className="inline-flex items-center px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-50 text-indigo-700 hover:bg-indigo-100 transition-colors"
                          >
                            Edit
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Slide-over Editor Panel */}
      {editorOpen && (
        <div className="fixed inset-0 z-50 overflow-hidden" aria-labelledby="slide-over-title" role="dialog" aria-modal="true">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-gray-500 bg-opacity-50 transition-opacity"
            onClick={handleCloseEditor}
            aria-hidden="true"
          ></div>

          {/* Panel */}
          <div className="fixed inset-y-0 right-0 flex max-w-full pl-10">
            <div className="w-screen max-w-2xl">
              <div className="flex h-full flex-col bg-white shadow-xl">
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                  <h3
                    id="slide-over-title"
                    className="text-lg font-semibold text-gray-900"
                  >
                    Edit {editingType === 'global_rules' ? 'Global Rule' : 'Plugin Metadata'}
                  </h3>
                  <button
                    type="button"
                    onClick={handleCloseEditor}
                    className="rounded-md text-gray-400 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    aria-label="Close panel"
                  >
                    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                {/* Editor */}
                <div className="flex-1 overflow-y-auto p-6">
                  <ResourceEditor
                    ref={editorRef}
                    value={getEditorValue(editingItem)}
                    onSubmit={handleSubmit}
                    onCancel={handleCloseEditor}
                    readOnly={submitting}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
