import { useState } from 'react';
import apiClient from '../api/client';

/**
 * Formats remaining seconds as MM:SS (zero-padded).
 * @param {number} seconds
 * @returns {string}
 */
export function formatRemainingTime(seconds) {
  if (seconds == null || seconds < 0) return '00:00';
  const totalSeconds = Math.floor(seconds);
  const mm = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
  const ss = String(totalSeconds % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

/**
 * EscalationBadge — displays escalation status badge inline next to rule names.
 *
 * Props:
 * - status: { state: 'idle'|'pending'|'escalated', grace_remaining_seconds?, escalated_at?, trigger_file? }
 * - ruleId: the alert rule ID (for acknowledge action)
 * - critical: boolean (whether the rule is critical)
 * - onAcknowledge: callback after successful acknowledgment
 */
export default function EscalationBadge({ status, ruleId, critical, onAcknowledge }) {
  const [acknowledging, setAcknowledging] = useState(false);

  // Render nothing if idle or no status
  if (!status || status.state === 'idle') {
    return null;
  }

  async function handleAcknowledge() {
    if (acknowledging) return;
    setAcknowledging(true);
    try {
      await apiClient.post(`/escalation/acknowledge/${ruleId}`);
      if (onAcknowledge) {
        onAcknowledge();
      }
    } catch (err) {
      console.error('Failed to acknowledge escalation:', err);
    } finally {
      setAcknowledging(false);
    }
  }

  // Pending state — yellow pulsing badge with countdown + acknowledge button
  if (status.state === 'pending') {
    const timeDisplay = formatRemainingTime(status.grace_remaining_seconds);
    return (
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800 animate-pulse">
          ⏳ Pending {timeDisplay}
        </span>
        <button
          onClick={handleAcknowledge}
          disabled={acknowledging}
          className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800 hover:bg-green-200 focus:outline-none focus:ring-1 focus:ring-green-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          title="Acknowledge and cancel escalation"
        >
          {acknowledging ? 'Ack...' : 'Acknowledge'}
        </button>
      </span>
    );
  }

  // Escalated state — red badge (with critical indicator if applicable)
  if (status.state === 'escalated') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">
        {critical ? '🔴⚡ Escalated (Critical)' : '🔴 Escalated'}
      </span>
    );
  }

  return null;
}
