import yaml from 'js-yaml';

/**
 * Parse editor content that may be JSON or YAML.
 * Tries JSON first, then falls back to YAML parsing.
 *
 * @param {string} content - The raw editor content string
 * @returns {{ data: object|null, error: string|null }}
 */
export function parseEditorContent(content) {
  if (!content || !content.trim()) {
    return { data: null, error: 'Editor content is empty.' };
  }

  // Try JSON first
  try {
    const data = JSON.parse(content);
    return { data, error: null };
  } catch {
    // Not valid JSON — try YAML
  }

  // Try YAML
  try {
    const data = yaml.load(content);
    if (data && typeof data === 'object') {
      return { data, error: null };
    }
    return { data: null, error: 'Parsed content is not a valid object.' };
  } catch (e) {
    return { data: null, error: `Invalid JSON/YAML: ${e.message}` };
  }
}

/**
 * Strip read-only fields that APISIX Admin API rejects on PUT/POST.
 * These are metadata fields added by APISIX internally.
 *
 * @param {object} obj - The parsed resource object
 * @returns {object} - Object without read-only fields
 */
export function stripReadOnlyFields(obj) {
  const {
    id,
    create_time,
    update_time,
    createdIndex,
    modifiedIndex,
    key,
    ...rest
  } = obj;
  return rest;
}
