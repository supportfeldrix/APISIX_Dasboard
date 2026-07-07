import { useState, useEffect, useCallback } from 'react';
import ResourceTable from '../components/ResourceTable';
import ConfirmDialog from '../components/ConfirmDialog';
import CertWarning from '../components/CertWarning';
import FileUploadField from '../components/FileUploadField';
import apiClient from '../api/client';
import { useAuthStore } from '../store/authStore';

/**
 * SSL — Page for managing APISIX SSL certificates.
 *
 * Features:
 *   - Fetches and displays SSL certificates list from /apisix/ssl
 *   - Upload form with certificate PEM and private key PEM textareas
 *   - File upload mode as alternative to text paste (independent per field)
 *   - Delete with ConfirmDialog (admin only)
 *   - CertWarning badge on expiry date column
 */
export default function SSL() {
  const [certificates, setCertificates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Upload form state
  const [certPem, setCertPem] = useState('');
  const [keyPem, setKeyPem] = useState('');
  const [snis, setSnis] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [uploadSuccess, setUploadSuccess] = useState('');

  // Mode toggles: 'paste' or 'upload' for each field independently
  const [certMode, setCertMode] = useState('paste');
  const [keyMode, setKeyMode] = useState('paste');

  // File state for upload mode
  const [certFile, setCertFile] = useState(null);
  const [keyFile, setKeyFile] = useState(null);

  // Server-side validation errors for file inputs
  const [certFileError, setCertFileError] = useState('');
  const [keyFileError, setKeyFileError] = useState('');

  // Delete confirmation state
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const role = useAuthStore((state) => state.role);

  const fetchCertificates = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await apiClient.get('/apisix/ssl');
      const list = response.data?.list || response.data?.node?.nodes || [];
      // Normalize the data — APISIX Admin API wraps items in { key, value } nodes
      const normalized = list.map((item) => {
        const value = item.value || item;
        return {
          id: value.id || item.key?.split('/').pop() || '—',
          snis: value.snis || [],
          validity_end: value.validity_end
            ? new Date(value.validity_end * 1000).toISOString()
            : value.expiry || null,
          status: value.status === 1 || value.status === 'enabled' ? 'enabled' : 'disabled',
        };
      });
      setCertificates(normalized);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch SSL certificates.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCertificates();
  }, [fetchCertificates]);

  // Table columns
  const columns = [
    { key: 'id', label: 'ID' },
    {
      key: 'snis',
      label: 'SNI Domains',
      render: (item) => (
        <span className="text-sm text-gray-700">
          {Array.isArray(item.snis) ? item.snis.join(', ') : item.snis || '—'}
        </span>
      ),
    },
    {
      key: 'validity_end',
      label: 'Expiry Date',
      render: (item) => (
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-700">
            {item.validity_end
              ? new Date(item.validity_end).toLocaleDateString()
              : '—'}
          </span>
          <CertWarning expiryDate={item.validity_end} />
        </div>
      ),
    },
    { key: 'status', label: 'Status' },
  ];

  /**
   * Parse server-side error detail and assign to the appropriate file error field.
   * The backend returns messages like "Invalid PEM certificate format" or "Invalid PEM private key format".
   */
  const assignServerErrors = (detail) => {
    const msg = typeof detail === 'string' ? detail : '';
    if (msg.toLowerCase().includes('certificate')) {
      setCertFileError(msg);
    } else if (msg.toLowerCase().includes('key')) {
      setKeyFileError(msg);
    } else {
      // Generic error — show as upload error
      setUploadError(msg || 'Failed to upload SSL certificate.');
    }
  };

  // Handle upload submit
  const handleUpload = async (e) => {
    e.preventDefault();
    setUploadError('');
    setUploadSuccess('');
    setCertFileError('');
    setKeyFileError('');
    setUploading(true);

    // Parse SNIs from comma-separated input
    const sniList = snis
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    // Determine if we're using file upload for either field
    const certIsFile = certMode === 'upload';
    const keyIsFile = keyMode === 'upload';

    // Validate based on mode
    if (certIsFile && !certFile) {
      setCertFileError('Please select a certificate file.');
      setUploading(false);
      return;
    }
    if (!certIsFile && !certPem.trim()) {
      setUploadError('Certificate PEM content is required.');
      setUploading(false);
      return;
    }
    if (keyIsFile && !keyFile) {
      setKeyFileError('Please select a private key file.');
      setUploading(false);
      return;
    }
    if (!keyIsFile && !keyPem.trim()) {
      setUploadError('Private key PEM content is required.');
      setUploading(false);
      return;
    }

    if (sniList.length === 0) {
      setUploadError('At least one SNI domain is required.');
      setUploading(false);
      return;
    }

    try {
      // If either field uses file upload mode, send multipart form to /ssl/upload
      if (certIsFile || keyIsFile) {
        const formData = new FormData();
        formData.append('snis', sniList.join(','));

        if (certIsFile && certFile) {
          formData.append('cert_file', certFile);
        }
        if (keyIsFile && keyFile) {
          formData.append('key_file', keyFile);
        }

        // For fields in paste mode, we still need to include the text content.
        // The backend /ssl/upload endpoint accepts optional cert_file and key_file.
        // If one field is in paste mode, we send the text as a form field.
        if (!certIsFile && certPem.trim()) {
          formData.append('cert_text', certPem.trim());
        }
        if (!keyIsFile && keyPem.trim()) {
          formData.append('key_text', keyPem.trim());
        }

        await apiClient.post('/ssl/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
      } else {
        // Both fields in paste mode — use existing JSON flow
        await apiClient.put('/apisix/ssl', {
          cert: certPem.trim(),
          key: keyPem.trim(),
          snis: sniList,
        });
      }

      setUploadSuccess('SSL certificate uploaded successfully.');
      setCertPem('');
      setKeyPem('');
      setSnis('');
      setCertFile(null);
      setKeyFile(null);
      fetchCertificates();
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (certIsFile || keyIsFile) {
        assignServerErrors(detail);
      } else {
        setUploadError(detail || 'Failed to upload SSL certificate.');
      }
    } finally {
      setUploading(false);
    }
  };

  // Handle delete
  const handleDeleteClick = (item) => {
    setDeleteTarget(item);
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await apiClient.delete(`/apisix/ssl/${deleteTarget.id}`);
      setDeleteTarget(null);
      fetchCertificates();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to delete certificate.');
    } finally {
      setDeleting(false);
    }
  };

  const handleDeleteCancel = () => {
    setDeleteTarget(null);
  };

  /**
   * ModeToggle — Inline toggle between "Paste" and "Upload" modes.
   */
  const ModeToggle = ({ mode, onModeChange, pasteLabel, uploadLabel }) => (
    <div className="inline-flex rounded-md shadow-sm" role="group">
      <button
        type="button"
        onClick={() => onModeChange('paste')}
        className={`px-3 py-1 text-xs font-medium rounded-l-md border ${
          mode === 'paste'
            ? 'bg-indigo-600 text-white border-indigo-600'
            : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
        }`}
      >
        {pasteLabel || 'Paste'}
      </button>
      <button
        type="button"
        onClick={() => onModeChange('upload')}
        className={`px-3 py-1 text-xs font-medium rounded-r-md border-t border-b border-r ${
          mode === 'upload'
            ? 'bg-indigo-600 text-white border-indigo-600'
            : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
        }`}
      >
        {uploadLabel || 'Upload'}
      </button>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">SSL Certificates</h1>
      </div>

      {/* Error banner */}
      {error && (
        <div
          className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* Upload form (admin only) */}
      {role === 'admin' && (
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">
            Upload SSL Certificate
          </h2>
          <form onSubmit={handleUpload} className="space-y-4">
            {uploadError && (
              <div
                className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm"
                role="alert"
              >
                {uploadError}
              </div>
            )}
            {uploadSuccess && (
              <div
                className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded text-sm"
                role="status"
              >
                {uploadSuccess}
              </div>
            )}

            <div>
              <label
                htmlFor="snis"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                SNI Domains (comma-separated)
              </label>
              <input
                id="snis"
                type="text"
                value={snis}
                onChange={(e) => setSnis(e.target.value)}
                placeholder="example.com, *.example.com"
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 text-sm"
              />
            </div>

            {/* Certificate field with mode toggle */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-sm font-medium text-gray-700">
                  Certificate PEM
                </label>
                <ModeToggle
                  mode={certMode}
                  onModeChange={(mode) => {
                    setCertMode(mode);
                    setCertFileError('');
                  }}
                  pasteLabel="Paste"
                  uploadLabel="Upload File"
                />
              </div>

              {certMode === 'paste' ? (
                <textarea
                  id="cert-pem"
                  value={certPem}
                  onChange={(e) => setCertPem(e.target.value)}
                  rows={6}
                  placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 font-mono text-sm"
                />
              ) : (
                <FileUploadField
                  label=""
                  accept=".pem,.crt,.cer,.key"
                  onChange={(file) => {
                    setCertFile(file);
                    setCertFileError('');
                  }}
                  error={certFileError}
                />
              )}
            </div>

            {/* Private Key field with mode toggle */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-sm font-medium text-gray-700">
                  Private Key PEM
                </label>
                <ModeToggle
                  mode={keyMode}
                  onModeChange={(mode) => {
                    setKeyMode(mode);
                    setKeyFileError('');
                  }}
                  pasteLabel="Paste"
                  uploadLabel="Upload File"
                />
              </div>

              {keyMode === 'paste' ? (
                <textarea
                  id="key-pem"
                  value={keyPem}
                  onChange={(e) => setKeyPem(e.target.value)}
                  rows={6}
                  placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 font-mono text-sm"
                />
              ) : (
                <FileUploadField
                  label=""
                  accept=".pem,.crt,.cer,.key"
                  onChange={(file) => {
                    setKeyFile(file);
                    setKeyFileError('');
                  }}
                  error={keyFileError}
                />
              )}
            </div>

            <button
              type="submit"
              disabled={uploading}
              className="inline-flex items-center px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 disabled:cursor-not-allowed text-white text-sm font-medium rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
            >
              {uploading ? 'Uploading...' : 'Upload Certificate'}
            </button>
          </form>
        </div>
      )}

      {/* Certificates table */}
      <ResourceTable
        columns={columns}
        data={certificates}
        loading={loading}
        role={role}
        onDelete={handleDeleteClick}
      />

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete SSL Certificate"
        message={`Are you sure you want to delete the SSL certificate "${deleteTarget?.id || ''}"? This action cannot be undone.`}
        confirmLabel={deleting ? 'Deleting...' : 'Delete'}
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
      />
    </div>
  );
}
