import React, { useState, useMemo } from 'react';

/**
 * ResourceTable — A generic, paginated table component for APISIX resources.
 *
 * Props:
 *   columns    — array of { key, label, render? } defining table columns
 *   data       — array of row objects
 *   onEdit     — callback(item) for edit action
 *   onDelete   — callback(item) for delete action
 *   onToggle   — optional callback(item) for enable/disable toggle
 *   pageSize   — rows per page (default 10)
 *   loading    — boolean for loading skeleton state
 *   role       — user role string to conditionally show admin-only actions
 */

function SkeletonRow({ colCount }) {
  return (
    <tr className="animate-pulse">
      {Array.from({ length: colCount }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 bg-gray-200 rounded w-3/4" />
        </td>
      ))}
      <td className="px-4 py-3">
        <div className="flex gap-2">
          <div className="h-8 w-16 bg-gray-200 rounded" />
          <div className="h-8 w-16 bg-gray-200 rounded" />
        </div>
      </td>
    </tr>
  );
}

export default function ResourceTable({
  columns = [],
  data = [],
  onEdit,
  onDelete,
  onToggle,
  pageSize = 10,
  loading = false,
  role = 'viewer',
}) {
  const [currentPage, setCurrentPage] = useState(1);

  // Reset to page 1 when data changes
  const totalPages = Math.max(1, Math.ceil(data.length / pageSize));

  // Ensure currentPage stays within bounds
  const safePage = Math.min(currentPage, totalPages);

  const paginatedData = useMemo(() => {
    const start = (safePage - 1) * pageSize;
    return data.slice(start, start + pageSize);
  }, [data, safePage, pageSize]);

  const handlePrevious = () => {
    setCurrentPage((prev) => Math.max(1, prev - 1));
  };

  const handleNext = () => {
    setCurrentPage((prev) => Math.min(totalPages, prev + 1));
  };

  // Number of columns including the actions column
  const totalColCount = columns.length + 1;

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200" role="table">
          <thead className="bg-gray-50">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                >
                  {col.label}
                </th>
              ))}
              <th
                scope="col"
                className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {loading ? (
              // Loading skeleton rows
              Array.from({ length: pageSize }).map((_, i) => (
                <SkeletonRow key={`skeleton-${i}`} colCount={columns.length} />
              ))
            ) : paginatedData.length === 0 ? (
              <tr>
                <td
                  colSpan={totalColCount}
                  className="px-4 py-8 text-center text-sm text-gray-500"
                >
                  No data available.
                </td>
              </tr>
            ) : (
              paginatedData.map((item, rowIndex) => (
                <tr
                  key={item.id || rowIndex}
                  className="hover:bg-gray-50 transition-colors"
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap"
                    >
                      {col.render ? col.render(item) : item[col.key] ?? '—'}
                    </td>
                  ))}
                  <td className="px-4 py-3 text-sm whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      {/* Edit button — always visible */}
                      <button
                        onClick={() => onEdit && onEdit(item)}
                        className="inline-flex items-center px-3 py-1.5 text-xs font-medium text-indigo-700 bg-indigo-50 rounded-md hover:bg-indigo-100 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
                        aria-label={`Edit ${item.name || item.id || 'item'}`}
                      >
                        Edit
                      </button>

                      {/* Toggle button — only if onToggle is provided */}
                      {onToggle && (
                        <button
                          onClick={() => onToggle(item)}
                          className={`inline-flex items-center px-3 py-1.5 text-xs font-medium rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1 ${
                            item.status === 1 || item.status === 'enabled'
                              ? 'text-amber-700 bg-amber-50 hover:bg-amber-100 focus:ring-amber-500'
                              : 'text-green-700 bg-green-50 hover:bg-green-100 focus:ring-green-500'
                          }`}
                          aria-label={`${
                            item.status === 1 || item.status === 'enabled'
                              ? 'Disable'
                              : 'Enable'
                          } ${item.name || item.id || 'item'}`}
                        >
                          {item.status === 1 || item.status === 'enabled'
                            ? 'Disable'
                            : 'Enable'}
                        </button>
                      )}

                      {/* Delete button — only visible for admin role */}
                      {role === 'admin' && (
                        <button
                          onClick={() => onDelete && onDelete(item)}
                          className="inline-flex items-center px-3 py-1.5 text-xs font-medium text-red-700 bg-red-50 rounded-md hover:bg-red-100 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1"
                          aria-label={`Delete ${item.name || item.id || 'item'}`}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination controls */}
      {!loading && data.length > 0 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 bg-gray-50">
          <p className="text-sm text-gray-600">
            Showing{' '}
            <span className="font-medium">{(safePage - 1) * pageSize + 1}</span>
            {' '}to{' '}
            <span className="font-medium">
              {Math.min(safePage * pageSize, data.length)}
            </span>
            {' '}of{' '}
            <span className="font-medium">{data.length}</span> results
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={handlePrevious}
              disabled={safePage <= 1}
              className="px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
              aria-label="Previous page"
            >
              Previous
            </button>
            <span className="text-sm text-gray-600">
              Page {safePage} of {totalPages}
            </span>
            <button
              onClick={handleNext}
              disabled={safePage >= totalPages}
              className="px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
              aria-label="Next page"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
