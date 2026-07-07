import client from './client';

/**
 * Notification API client module.
 * Provides functions for all notification-related endpoints.
 */

// ─── Alert Rules ────────────────────────────────────────────────────────────

/**
 * Fetch paginated list of alert rules.
 * @param {Object} params - Query parameters
 * @param {number} [params.page=1] - Page number
 * @param {number} [params.page_size=25] - Items per page (max 100)
 * @returns {Promise} Axios response with paginated rules
 */
export function getRules({ page = 1, page_size = 25 } = {}) {
  return client.get('/notifications/rules', { params: { page, page_size } });
}

/**
 * Fetch a single alert rule by ID.
 * @param {number|string} id - Alert rule ID
 * @returns {Promise} Axios response with rule data
 */
export function getRule(id) {
  return client.get(`/notifications/rules/${id}`);
}

/**
 * Create a new alert rule.
 * @param {Object} data - Rule payload
 * @param {string} data.name - Rule name (1-128 chars, alphanumeric/hyphens/underscores)
 * @param {string} data.route_id - Target route ID
 * @param {string} data.condition_type - One of: JWT_FAILURE, UPSTREAM_ERROR, HIGH_ERROR_RATE, HEALTH_CHECK_FAILURE
 * @param {number} data.threshold - Threshold value
 * @param {string[]} data.recipients - List of recipient email addresses (1-10)
 * @param {number} data.cooldown_seconds - Cooldown period in seconds (60-86400)
 * @param {boolean} [data.enabled=true] - Whether the rule is enabled
 * @param {boolean} [data.notify_controlm=false] - Enable ControlM phone-call escalation
 * @param {boolean} [data.critical=false] - Critical flag (bypasses grace period, immediate escalation)
 * @param {string} [data.health_check_url] - Health check URL (for HEALTH_CHECK_FAILURE)
 * @param {number} [data.health_check_interval] - Probe interval in seconds
 * @param {number} [data.health_check_failures_threshold] - Consecutive failures before alert
 * @returns {Promise} Axios response with created rule
 */
export function createRule(data) {
  return client.post('/notifications/rules', data);
}

/**
 * Update an existing alert rule.
 * @param {number|string} id - Alert rule ID
 * @param {Object} data - Fields to update (same shape as createRule, includes notify_controlm and critical)
 * @returns {Promise} Axios response with updated rule
 */
export function updateRule(id, data) {
  return client.put(`/notifications/rules/${id}`, data);
}

/**
 * Delete an alert rule.
 * @param {number|string} id - Alert rule ID
 * @returns {Promise} Axios response
 */
export function deleteRule(id) {
  return client.delete(`/notifications/rules/${id}`);
}

/**
 * Toggle an alert rule's enabled status.
 * @param {number|string} id - Alert rule ID
 * @returns {Promise} Axios response with updated rule
 */
export function toggleRule(id) {
  return client.patch(`/notifications/rules/${id}/toggle`);
}

// ─── Notification Logs ──────────────────────────────────────────────────────

/**
 * Fetch paginated and filtered notification logs.
 * @param {Object} params - Query/filter parameters
 * @param {string} [params.route_id] - Filter by route ID
 * @param {string} [params.condition_type] - Filter by condition type
 * @param {string} [params.delivery_status] - Filter by delivery status (SENT, FAILED, RETRYING)
 * @param {string} [params.date_from] - Filter from date (ISO string)
 * @param {string} [params.date_to] - Filter to date (ISO string)
 * @param {number} [params.page=1] - Page number
 * @param {number} [params.page_size=25] - Items per page
 * @returns {Promise} Axios response with paginated logs
 */
export function getLogs(params = {}) {
  const query = {};
  if (params.route_id) query.route_id = params.route_id;
  if (params.condition_type) query.condition_type = params.condition_type;
  if (params.delivery_status) query.delivery_status = params.delivery_status;
  if (params.date_from) query.date_from = params.date_from;
  if (params.date_to) query.date_to = params.date_to;
  query.page = params.page || 1;
  query.page_size = params.page_size || 25;

  return client.get('/notifications/logs', { params: query });
}

// ─── Test Email ─────────────────────────────────────────────────────────────

/**
 * Send a test email to verify SMTP configuration.
 * @param {string} recipient - Email address to send test to
 * @returns {Promise} Axios response with delivery status
 */
export function sendTestEmail(recipient) {
  return client.post(`/notifications/test-email?recipient=${encodeURIComponent(recipient)}`);
}

// ─── Scheduler Status ───────────────────────────────────────────────────────

/**
 * Get the current status of the background notification scheduler.
 * @returns {Promise} Axios response with scheduler status
 */
export function getStatus() {
  return client.get('/notifications/status');
}
