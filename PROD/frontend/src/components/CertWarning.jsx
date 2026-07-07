import React from 'react';

/**
 * CertWarning — Badge component that displays SSL certificate expiry warnings.
 *
 * Props:
 *   expiryDate — ISO date string or Date object representing the certificate expiry date
 *
 * Behavior:
 *   - Expired or within 7 days: red critical badge
 *   - Within 30 days (but more than 7): amber warning badge
 *   - More than 30 days away: renders nothing
 */
function CertWarning({ expiryDate }) {
  if (!expiryDate) return null;

  const expiry = expiryDate instanceof Date ? expiryDate : new Date(expiryDate);

  // Guard against invalid dates
  if (isNaN(expiry.getTime())) return null;

  const now = new Date();
  const diffMs = expiry.getTime() - now.getTime();
  const daysUntilExpiry = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

  // More than 30 days away — no badge
  if (daysUntilExpiry > 30) return null;

  const isExpired = daysUntilExpiry <= 0;
  const isCritical = daysUntilExpiry <= 7;

  const badgeText = isExpired
    ? 'Expired'
    : `Expires in ${daysUntilExpiry} day${daysUntilExpiry === 1 ? '' : 's'}`;

  const badgeClasses = isCritical
    ? 'bg-red-100 text-red-800'
    : 'bg-yellow-100 text-yellow-800';

  const dotClasses = isCritical
    ? 'bg-red-400'
    : 'bg-yellow-400';

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${badgeClasses}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full mr-1.5 ${dotClasses}`} aria-hidden="true" />
      {badgeText}
    </span>
  );
}

export default CertWarning;
