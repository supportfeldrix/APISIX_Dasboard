import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * AlertRuleForm — Modal form for creating and editing alert rules.
 *
 * Props:
 *   isOpen       — boolean controlling visibility
 *   onClose      — callback to close the modal
 *   onSubmit     — callback(formData) when form is valid and submitted
 *   initialData  — null for create mode, object for edit mode
 *   routes       — array of available routes [{ id, name, uri, ... }]
 */

/** Case-insensitive patterns that auto-check the "critical" toggle */
const CRITICAL_PATTERNS = [
  'realtimewsprovider',
  'realtimescreening',
  'rts',
  'actimize',
  'actone',
  'rcm',
];

/**
 * Check if a route_id or route_name matches any critical pattern (case-insensitive).
 */
function matchesCriticalPattern(value) {
  if (!value) return false;
  const lower = value.toLowerCase();
  return CRITICAL_PATTERNS.some((pattern) => lower.includes(pattern));
}

const CONDITION_TYPES = [
  { value: 'JWT_FAILURE', label: 'JWT Failure (401/403)' },
  { value: 'UPSTREAM_ERROR', label: 'Upstream Error (502/503/504)' },
  { value: 'CLIENT_ERROR', label: 'Client Error (4xx)' },
  { value: 'HIGH_ERROR_RATE', label: 'High Error Rate (%)' },
  { value: 'HEALTH_CHECK_FAILURE', label: 'Health Check Failure' },
  { value: 'POD_HEALTH', label: 'Pod Health (OOM/Restarts)' },
];

const NAME_PATTERN = /^[a-zA-Z0-9_-]+$/;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function getThresholdRange(conditionType) {
  if (conditionType === 'HIGH_ERROR_RATE') {
    return { min: 1, max: 100 };
  }
  return { min: 1, max: 10000 };
}

function getThresholdLabel(conditionType) {
  if (conditionType === 'HIGH_ERROR_RATE') {
    return 'Threshold (1-100%)';
  }
  return 'Threshold (1-10000 count)';
}

export default function AlertRuleForm({
  isOpen,
  onClose,
  onSubmit,
  initialData = null,
  routes = [],
}) {
  const dialogRef = useRef(null);
  const firstInputRef = useRef(null);

  // Form state
  const [name, setName] = useState('');
  const [routeId, setRouteId] = useState('');
  const [conditionType, setConditionType] = useState('JWT_FAILURE');
  const [threshold, setThreshold] = useState('');
  const [recipients, setRecipients] = useState([]);
  const [emailInput, setEmailInput] = useState('');
  const [cooldownSeconds, setCooldownSeconds] = useState('300');
  const [enabled, setEnabled] = useState(true);
  const [healthCheckUrl, setHealthCheckUrl] = useState('');
  const [healthCheckInterval, setHealthCheckInterval] = useState('60');
  const [healthCheckFailuresThreshold, setHealthCheckFailuresThreshold] = useState('3');

  // ControlM Escalation fields
  const [notifyControlm, setNotifyControlm] = useState(false);
  const [critical, setCritical] = useState(false);

  // Validation errors
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);

  const isEditMode = initialData !== null;

  // Populate form when initialData changes (edit mode)
  useEffect(() => {
    if (isOpen && initialData) {
      setName(initialData.name || '');
      setRouteId(initialData.route_id || '');
      setConditionType(initialData.condition_type || 'JWT_FAILURE');
      setThreshold(String(initialData.threshold || ''));
      setRecipients(initialData.recipients || []);
      setCooldownSeconds(String(initialData.cooldown_seconds || '300'));
      setEnabled(initialData.enabled !== undefined ? initialData.enabled : true);
      setHealthCheckUrl(initialData.health_check_url || '');
      setHealthCheckInterval(String(initialData.health_check_interval || '60'));
      setHealthCheckFailuresThreshold(String(initialData.health_check_failures_threshold || '3'));
      setNotifyControlm(initialData.notify_controlm || false);
      setCritical(initialData.critical || false);
      setEmailInput('');
      setErrors({});
    } else if (isOpen && !initialData) {
      // Reset form for create mode
      setName('');
      setRouteId('');
      setConditionType('JWT_FAILURE');
      setThreshold('');
      setRecipients([]);
      setEmailInput('');
      setCooldownSeconds('300');
      setEnabled(true);
      setHealthCheckUrl('');
      setHealthCheckInterval('60');
      setHealthCheckFailuresThreshold('3');
      setNotifyControlm(false);
      setCritical(false);
      setErrors({});
    }
  }, [isOpen, initialData]);

  // Focus first input when modal opens
  useEffect(() => {
    if (isOpen && firstInputRef.current) {
      setTimeout(() => firstInputRef.current.focus(), 50);
    }
  }, [isOpen]);

  // Auto-check "critical" toggle when route_id matches a critical pattern
  useEffect(() => {
    if (!isOpen) return;
    // Look up the route name from the routes array
    const selectedRoute = routes.find((r) => String(r.id) === String(routeId));
    const routeName = selectedRoute?.name || '';
    // Check if route_id or route_name matches any critical pattern
    if (matchesCriticalPattern(routeId) || matchesCriticalPattern(routeName)) {
      setCritical(true);
    }
  }, [routeId, routes, isOpen]);

  // ESC key closes the modal
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose?.();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Focus trap
  const handleKeyDown = useCallback((e) => {
    if (e.key !== 'Tab' || !dialogRef.current) return;

    const focusableElements = dialogRef.current.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );

    if (focusableElements.length === 0) return;

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === firstElement) {
        e.preventDefault();
        lastElement.focus();
      }
    } else {
      if (document.activeElement === lastElement) {
        e.preventDefault();
        firstElement.focus();
      }
    }
  }, []);

  // ─── Validation ─────────────────────────────────────────────────────────

  function validateField(field, value) {
    switch (field) {
      case 'name':
        if (!value || value.length === 0) return 'Name is required';
        if (value.length > 128) return 'Name must be 128 characters or fewer';
        if (!NAME_PATTERN.test(value)) return 'Only alphanumeric, hyphens, and underscores allowed';
        return '';

      case 'route_id':
        if (!value) {
          if (conditionType === 'POD_HEALTH') return 'Pod name pattern is required';
          return 'Route selection is required';
        }
        return '';

      case 'threshold': {
        const num = parseInt(value, 10);
        const range = getThresholdRange(conditionType);
        if (!value || isNaN(num)) return 'Threshold is required';
        if (num < range.min || num > range.max) return `Must be between ${range.min} and ${range.max}`;
        return '';
      }

      case 'recipients':
        if (!value || value.length === 0) return 'At least one recipient is required';
        if (value.length > 10) return 'Maximum 10 recipients allowed';
        return '';

      case 'cooldown_seconds': {
        const num = parseInt(value, 10);
        if (!value || isNaN(num)) return 'Cooldown is required';
        if (num < 60 || num > 86400) return 'Must be between 60 and 86400 seconds';
        return '';
      }

      case 'health_check_url':
        if (conditionType === 'HEALTH_CHECK_FAILURE') {
          if (!value || value.trim().length === 0) return 'Health check URL is required';
          try {
            new URL(value);
          } catch {
            return 'Must be a valid URL';
          }
        }
        return '';

      case 'health_check_interval': {
        if (conditionType !== 'HEALTH_CHECK_FAILURE') return '';
        const num = parseInt(value, 10);
        if (!value || isNaN(num)) return 'Interval is required';
        if (num < 10 || num > 3600) return 'Must be between 10 and 3600 seconds';
        return '';
      }

      case 'health_check_failures_threshold': {
        if (conditionType !== 'HEALTH_CHECK_FAILURE') return '';
        const num = parseInt(value, 10);
        if (!value || isNaN(num)) return 'Failure threshold is required';
        if (num < 1 || num > 10) return 'Must be between 1 and 10';
        return '';
      }

      default:
        return '';
    }
  }

  function validateAll() {
    const newErrors = {};

    const nameErr = validateField('name', name);
    if (nameErr) newErrors.name = nameErr;

    const routeErr = validateField('route_id', routeId);
    if (routeErr) newErrors.route_id = routeErr;

    const thresholdErr = validateField('threshold', threshold);
    if (thresholdErr) newErrors.threshold = thresholdErr;

    const recipientsErr = validateField('recipients', recipients);
    if (recipientsErr) newErrors.recipients = recipientsErr;

    const cooldownErr = validateField('cooldown_seconds', cooldownSeconds);
    if (cooldownErr) newErrors.cooldown_seconds = cooldownErr;

    if (conditionType === 'HEALTH_CHECK_FAILURE') {
      const urlErr = validateField('health_check_url', healthCheckUrl);
      if (urlErr) newErrors.health_check_url = urlErr;

      const intervalErr = validateField('health_check_interval', healthCheckInterval);
      if (intervalErr) newErrors.health_check_interval = intervalErr;

      const failuresErr = validateField('health_check_failures_threshold', healthCheckFailuresThreshold);
      if (failuresErr) newErrors.health_check_failures_threshold = failuresErr;
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }

  function handleBlur(field, value) {
    const err = validateField(field, value);
    setErrors((prev) => {
      const next = { ...prev };
      if (err) {
        next[field] = err;
      } else {
        delete next[field];
      }
      return next;
    });
  }

  // ─── Email Tag Input ────────────────────────────────────────────────────

  function addEmail() {
    const email = emailInput.trim();
    if (!email) return;

    if (!EMAIL_PATTERN.test(email)) {
      setErrors((prev) => ({ ...prev, email_input: 'Invalid email format' }));
      return;
    }

    if (recipients.includes(email)) {
      setErrors((prev) => ({ ...prev, email_input: 'Email already added' }));
      return;
    }

    if (recipients.length >= 10) {
      setErrors((prev) => ({ ...prev, email_input: 'Maximum 10 recipients' }));
      return;
    }

    setRecipients((prev) => [...prev, email]);
    setEmailInput('');
    setErrors((prev) => {
      const next = { ...prev };
      delete next.email_input;
      delete next.recipients;
      return next;
    });
  }

  function removeEmail(email) {
    setRecipients((prev) => prev.filter((e) => e !== email));
  }

  function handleEmailKeyDown(e) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addEmail();
    }
    // Backspace removes last tag when input is empty
    if (e.key === 'Backspace' && emailInput === '' && recipients.length > 0) {
      setRecipients((prev) => prev.slice(0, -1));
    }
  }

  // ─── Submit ─────────────────────────────────────────────────────────────

  async function handleSubmit(e) {
    e.preventDefault();

    if (!validateAll()) return;

    setSubmitting(true);

    const formData = {
      name,
      route_id: routeId,
      condition_type: conditionType,
      threshold: parseInt(threshold, 10),
      recipients,
      cooldown_seconds: parseInt(cooldownSeconds, 10),
      enabled,
      notify_controlm: notifyControlm,
      critical,
    };

    if (conditionType === 'HEALTH_CHECK_FAILURE') {
      formData.health_check_url = healthCheckUrl;
      formData.health_check_interval = parseInt(healthCheckInterval, 10);
      formData.health_check_failures_threshold = parseInt(healthCheckFailuresThreshold, 10);
    }

    try {
      await onSubmit(formData);
    } finally {
      setSubmitting(false);
    }
  }

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto"
      onKeyDown={handleKeyDown}
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
        aria-hidden="true"
        onClick={onClose}
      />

      {/* Modal container */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="alert-rule-form-title"
        className="relative z-10 w-full max-w-lg mx-4 my-8 rounded-lg bg-white shadow-xl max-h-[90vh] flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2
            id="alert-rule-form-title"
            className="text-lg font-semibold text-gray-900"
          >
            {isEditMode ? 'Edit Alert Rule' : 'Create Alert Rule'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md text-gray-400 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            aria-label="Close"
          >
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Form body */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {/* Rule Name */}
          <div>
            <label htmlFor="rule-name" className="block text-sm font-medium text-gray-700">
              Rule Name
            </label>
            <input
              ref={firstInputRef}
              id="rule-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => handleBlur('name', name)}
              maxLength={128}
              placeholder="my-alert-rule"
              className={`mt-1 block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                errors.name ? 'border-red-300 focus:ring-red-500' : 'border-gray-300'
              }`}
            />
            {errors.name && (
              <p className="mt-1 text-xs text-red-600">{errors.name}</p>
            )}
            <p className="mt-1 text-xs text-gray-500">1-128 characters, alphanumeric, hyphens, underscores</p>
          </div>

          {/* Route Selector — not required for POD_HEALTH */}
          {conditionType === 'POD_HEALTH' ? (
            <div>
              <label htmlFor="route-select" className="block text-sm font-medium text-gray-700">
                Pod Name Pattern
              </label>
              <input
                id="route-select"
                type="text"
                value={routeId}
                onChange={(e) => setRouteId(e.target.value)}
                onBlur={() => handleBlur('route_id', routeId)}
                placeholder="e.g. apisix (matches pods containing this text)"
                className={`mt-1 block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  errors.route_id ? 'border-red-300 focus:ring-red-500' : 'border-gray-300'
                }`}
              />
              {errors.route_id && (
                <p className="mt-1 text-xs text-red-600">{errors.route_id}</p>
              )}
              <p className="mt-1 text-xs text-gray-500">Enter a pod name filter (e.g. "apisix" matches apisix-0, apisix-1)</p>
            </div>
          ) : (
            <div>
              <label htmlFor="route-select" className="block text-sm font-medium text-gray-700">
                Target Route
              </label>
              <select
                id="route-select"
                value={routeId}
                onChange={(e) => setRouteId(e.target.value)}
                onBlur={() => handleBlur('route_id', routeId)}
                className={`mt-1 block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  errors.route_id ? 'border-red-300 focus:ring-red-500' : 'border-gray-300'
                }`}
              >
                <option value="">Select a route...</option>
                {routes.map((route) => (
                  <option key={route.id} value={route.id}>
                    {route.name || route.uri || route.id}
                  </option>
                ))}
              </select>
              {errors.route_id && (
                <p className="mt-1 text-xs text-red-600">{errors.route_id}</p>
              )}
            </div>
          )}

          {/* Condition Type */}
          <div>
            <label htmlFor="condition-type" className="block text-sm font-medium text-gray-700">
              Condition Type
            </label>
            <select
              id="condition-type"
              value={conditionType}
              onChange={(e) => {
                setConditionType(e.target.value);
                // Clear threshold error when switching types (range changes)
                setErrors((prev) => {
                  const next = { ...prev };
                  delete next.threshold;
                  return next;
                });
              }}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              {CONDITION_TYPES.map((ct) => (
                <option key={ct.value} value={ct.value}>
                  {ct.label}
                </option>
              ))}
            </select>
          </div>

          {/* Threshold */}
          <div>
            <label htmlFor="threshold" className="block text-sm font-medium text-gray-700">
              {getThresholdLabel(conditionType)}
            </label>
            <input
              id="threshold"
              type="number"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              onBlur={() => handleBlur('threshold', threshold)}
              min={getThresholdRange(conditionType).min}
              max={getThresholdRange(conditionType).max}
              className={`mt-1 block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                errors.threshold ? 'border-red-300 focus:ring-red-500' : 'border-gray-300'
              }`}
            />
            {errors.threshold && (
              <p className="mt-1 text-xs text-red-600">{errors.threshold}</p>
            )}
          </div>

          {/* Recipients (Tag Input) */}
          <div>
            <label htmlFor="email-input" className="block text-sm font-medium text-gray-700">
              Recipients (1-10 email addresses)
            </label>
            <div
              className={`mt-1 flex flex-wrap items-center gap-1 rounded-md border px-2 py-1.5 min-h-[38px] focus-within:ring-2 focus-within:ring-indigo-500 ${
                errors.recipients || errors.email_input ? 'border-red-300' : 'border-gray-300'
              }`}
            >
              {recipients.map((email) => (
                <span
                  key={email}
                  className="inline-flex items-center gap-1 rounded-md bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-800"
                >
                  {email}
                  <button
                    type="button"
                    onClick={() => removeEmail(email)}
                    className="text-indigo-600 hover:text-indigo-900 focus:outline-none"
                    aria-label={`Remove ${email}`}
                  >
                    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </span>
              ))}
              <input
                id="email-input"
                type="text"
                value={emailInput}
                onChange={(e) => {
                  setEmailInput(e.target.value);
                  setErrors((prev) => {
                    const next = { ...prev };
                    delete next.email_input;
                    return next;
                  });
                }}
                onKeyDown={handleEmailKeyDown}
                onBlur={() => {
                  if (emailInput.trim()) addEmail();
                  handleBlur('recipients', recipients);
                }}
                placeholder={recipients.length === 0 ? 'Enter email and press Enter' : ''}
                className="flex-1 min-w-[150px] border-none outline-none text-sm py-0.5"
              />
            </div>
            {errors.email_input && (
              <p className="mt-1 text-xs text-red-600">{errors.email_input}</p>
            )}
            {errors.recipients && !errors.email_input && (
              <p className="mt-1 text-xs text-red-600">{errors.recipients}</p>
            )}
            <p className="mt-1 text-xs text-gray-500">Press Enter or comma to add an email</p>
          </div>

          {/* Cooldown */}
          <div>
            <label htmlFor="cooldown" className="block text-sm font-medium text-gray-700">
              Cooldown (60-86400 seconds)
            </label>
            <input
              id="cooldown"
              type="number"
              value={cooldownSeconds}
              onChange={(e) => setCooldownSeconds(e.target.value)}
              onBlur={() => handleBlur('cooldown_seconds', cooldownSeconds)}
              min={60}
              max={86400}
              className={`mt-1 block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                errors.cooldown_seconds ? 'border-red-300 focus:ring-red-500' : 'border-gray-300'
              }`}
            />
            {errors.cooldown_seconds && (
              <p className="mt-1 text-xs text-red-600">{errors.cooldown_seconds}</p>
            )}
          </div>

          {/* Enabled Toggle */}
          <div className="flex items-center justify-between">
            <label htmlFor="enabled-toggle" className="text-sm font-medium text-gray-700">
              Enabled
            </label>
            <button
              id="enabled-toggle"
              type="button"
              role="switch"
              aria-checked={enabled}
              onClick={() => setEnabled((prev) => !prev)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 ${
                enabled ? 'bg-indigo-600' : 'bg-gray-200'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  enabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {/* ControlM Escalation Section */}
          <div className="space-y-4 rounded-md border border-gray-200 bg-gray-50 p-4">
            <h3 className="text-sm font-medium text-gray-800">ControlM Escalation</h3>

            {/* Enable ControlM Escalation Toggle */}
            <div className="flex items-center justify-between">
              <label htmlFor="notify-controlm-toggle" className="text-sm font-medium text-gray-700">
                Enable ControlM Escalation
              </label>
              <button
                id="notify-controlm-toggle"
                type="button"
                role="switch"
                aria-checked={notifyControlm}
                onClick={() => setNotifyControlm((prev) => !prev)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 ${
                  notifyControlm ? 'bg-indigo-600' : 'bg-gray-200'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    notifyControlm ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

            {/* Critical (Immediate Escalation) Toggle */}
            <div className="flex items-center justify-between">
              <div>
                <label htmlFor="critical-toggle" className="text-sm font-medium text-gray-700">
                  Critical (Immediate Escalation)
                </label>
                <p className="text-xs text-gray-500">Critical rules bypass grace period and escalate immediately</p>
              </div>
              <button
                id="critical-toggle"
                type="button"
                role="switch"
                aria-checked={critical}
                onClick={() => setCritical((prev) => !prev)}
                className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 ${
                  critical ? 'bg-red-600' : 'bg-gray-200'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    critical ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
          </div>

          {/* Health Check Fields (conditional) */}
          {conditionType === 'HEALTH_CHECK_FAILURE' && (
            <div className="space-y-4 rounded-md border border-gray-200 bg-gray-50 p-4">
              <h3 className="text-sm font-medium text-gray-800">Health Check Configuration</h3>

              {/* Health Check URL */}
              <div>
                <label htmlFor="health-check-url" className="block text-sm font-medium text-gray-700">
                  Health Check URL
                </label>
                <input
                  id="health-check-url"
                  type="text"
                  value={healthCheckUrl}
                  onChange={(e) => setHealthCheckUrl(e.target.value)}
                  onBlur={() => handleBlur('health_check_url', healthCheckUrl)}
                  placeholder="https://example.com/health"
                  className={`mt-1 block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                    errors.health_check_url ? 'border-red-300 focus:ring-red-500' : 'border-gray-300'
                  }`}
                />
                {errors.health_check_url && (
                  <p className="mt-1 text-xs text-red-600">{errors.health_check_url}</p>
                )}
              </div>

              {/* Health Check Interval */}
              <div>
                <label htmlFor="health-check-interval" className="block text-sm font-medium text-gray-700">
                  Probe Interval (10-3600 seconds)
                </label>
                <input
                  id="health-check-interval"
                  type="number"
                  value={healthCheckInterval}
                  onChange={(e) => setHealthCheckInterval(e.target.value)}
                  onBlur={() => handleBlur('health_check_interval', healthCheckInterval)}
                  min={10}
                  max={3600}
                  className={`mt-1 block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                    errors.health_check_interval ? 'border-red-300 focus:ring-red-500' : 'border-gray-300'
                  }`}
                />
                {errors.health_check_interval && (
                  <p className="mt-1 text-xs text-red-600">{errors.health_check_interval}</p>
                )}
              </div>

              {/* Health Check Failures Threshold */}
              <div>
                <label htmlFor="health-check-failures" className="block text-sm font-medium text-gray-700">
                  Consecutive Failures Before Alert (1-10)
                </label>
                <input
                  id="health-check-failures"
                  type="number"
                  value={healthCheckFailuresThreshold}
                  onChange={(e) => setHealthCheckFailuresThreshold(e.target.value)}
                  onBlur={() => handleBlur('health_check_failures_threshold', healthCheckFailuresThreshold)}
                  min={1}
                  max={10}
                  className={`mt-1 block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                    errors.health_check_failures_threshold ? 'border-red-300 focus:ring-red-500' : 'border-gray-300'
                  }`}
                />
                {errors.health_check_failures_threshold && (
                  <p className="mt-1 text-xs text-red-600">{errors.health_check_failures_threshold}</p>
                )}
              </div>
            </div>
          )}
        </form>

        {/* Footer with action buttons */}
        <div className="flex justify-end gap-3 px-6 py-4 border-t border-gray-200">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Saving...' : isEditMode ? 'Update Rule' : 'Create Rule'}
          </button>
        </div>
      </div>
    </div>
  );
}
