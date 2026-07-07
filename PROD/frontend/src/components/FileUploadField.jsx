import React, { useRef, useState } from 'react';

/**
 * formatFileSize — Formats a file size in bytes to a human-readable string.
 *
 * Rules:
 *   - < 1024 bytes → "{n} bytes"
 *   - [1024, 1048576) → "{n/1024} KB" with 1 decimal place
 *   - >= 1048576 → "{n/1048576} MB" with 1 decimal place
 */
export function formatFileSize(bytes) {
  if (bytes < 1024) {
    return `${bytes} bytes`;
  }
  if (bytes < 1048576) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

const MAX_FILE_SIZE = 1048576; // 1 MB

/**
 * FileUploadField — Reusable file input component for SSL certificate/key uploads.
 *
 * Props:
 *   label    — Label text displayed above the file input
 *   accept   — Comma-separated file extensions (default: ".pem,.crt,.cer,.key")
 *   onChange — Callback invoked with the selected File object or null when cleared
 *   error    — Optional error message string (e.g. from server-side validation)
 */
export default function FileUploadField({
  label,
  accept = '.pem,.crt,.cer,.key',
  onChange,
  error,
}) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [sizeError, setSizeError] = useState('');
  const inputRef = useRef(null);

  const handleFileChange = (e) => {
    const file = e.target.files?.[0] || null;

    if (!file) {
      setSelectedFile(null);
      setSizeError('');
      onChange?.(null);
      return;
    }

    if (file.size > MAX_FILE_SIZE) {
      setSelectedFile(file);
      setSizeError('File exceeds the maximum allowed size (1 MB)');
      onChange?.(null);
      return;
    }

    setSelectedFile(file);
    setSizeError('');
    onChange?.(file);
  };

  const handleRemove = () => {
    setSelectedFile(null);
    setSizeError('');
    onChange?.(null);
    // Reset the native input so the same file can be re-selected
    if (inputRef.current) {
      inputRef.current.value = '';
    }
  };

  const displayError = sizeError || error;

  return (
    <div className="space-y-2">
      {label && (
        <label className="block text-sm font-medium text-gray-700">
          {label}
        </label>
      )}

      {!selectedFile ? (
        /* Empty state — show file picker button */
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="inline-flex items-center rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            {/* Upload icon */}
            <svg
              className="mr-2 h-4 w-4 text-gray-400"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
              />
            </svg>
            Choose file
          </button>
          <span className="text-sm text-gray-500">No file selected</span>
        </div>
      ) : (
        /* File selected state — show filename, size, and remove button */
        <div className="flex items-center gap-3 rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
          {/* File icon */}
          <svg
            className="h-5 w-5 flex-shrink-0 text-gray-400"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
            />
          </svg>

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-gray-900">
              {selectedFile.name}
            </p>
            <p className="text-xs text-gray-500">
              {formatFileSize(selectedFile.size)}
            </p>
          </div>

          {/* Remove button */}
          <button
            type="button"
            onClick={handleRemove}
            className="rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Remove file"
          >
            <svg
              className="h-4 w-4"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>
      )}

      {/* Hidden native file input */}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={handleFileChange}
        className="hidden"
        aria-hidden="true"
      />

      {/* Error message */}
      {displayError && (
        <p className="text-sm text-red-600" role="alert">
          {displayError}
        </p>
      )}
    </div>
  );
}
