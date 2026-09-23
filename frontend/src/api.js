// Single place that knows how to reach the FastAPI backend.
//
// In development the Vite proxy forwards /api -> http://127.0.0.1:8000.
// Set VITE_API_BASE_URL in a .env file to point at a different backend.

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

export const OFFLINE_MESSAGE =
  'The detection service is currently unavailable. Check that the backend is ' +
  'running on http://127.0.0.1:8000 and try again.'

export const TIMEOUT_MESSAGE =
  'The detection service took too long to respond. BERT inference on CPU can ' +
  'be slow — please try again.'

// BERT inference on CPU takes noticeably longer than the Naive Bayes model,
// so the ceiling is generous. It exists to stop a hung backend leaving the UI
// spinning forever, not to cut off a slow-but-working request.
const REQUEST_TIMEOUT_MS = 60_000

/** Turn a FastAPI error body into one readable sentence. */
function describeError(payload, status) {
  const detail = payload?.detail

  if (typeof detail === 'string') return detail

  // Pydantic validation errors arrive as a list of {loc, msg, type}.
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0]
    if (typeof first?.msg === 'string') {
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : null
      return field ? `${field}: ${first.msg}` : first.msg
    }
  }

  if (status >= 500) {
    return 'The detection service hit an internal error. Check the backend logs.'
  }
  return `The backend returned an error (HTTP ${status}).`
}

async function request(path, options = {}) {
  // Combine the caller's abort signal with our own timeout.
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(new Error('timeout')), REQUEST_TIMEOUT_MS)

  if (options.signal) {
    if (options.signal.aborted) controller.abort()
    else options.signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  let response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, signal: controller.signal })
  } catch (error) {
    // A caller-initiated abort must stay an AbortError so callers can ignore it.
    if (options.signal?.aborted) {
      const aborted = new Error('Request cancelled')
      aborted.name = 'AbortError'
      throw aborted
    }
    throw new Error(controller.signal.aborted ? TIMEOUT_MESSAGE : OFFLINE_MESSAGE)
  } finally {
    clearTimeout(timer)
  }

  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const error = new Error(describeError(payload, response.status))
    error.status = response.status
    throw error
  }

  return payload
}

export function predictEmail(text, signal) {
  return request('/predict', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
    signal,
  })
}

export function checkHealth() {
  return request('/health')
}

export function fetchMetrics() {
  return request('/metrics')
}

export function fetchStats() {
  return request('/stats')
}

export function fetchMessages(box, limit = 200) {
  return request(`/messages?box=${encodeURIComponent(box)}&limit=${limit}`)
}

export function moveMessage(id, to) {
  return request(`/messages/${encodeURIComponent(id)}/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ to }),
  })
}
