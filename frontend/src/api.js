// Single place that knows how to reach the FastAPI backend.
//
// In development the Vite proxy forwards /api -> http://127.0.0.1:8000.
// Set VITE_API_BASE_URL in a .env file to point at a different backend.

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

const OFFLINE_MESSAGE =
  "Can't reach the prediction service. Make sure the backend is running on http://127.0.0.1:8000."

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, options)
  } catch {
    throw new Error(OFFLINE_MESSAGE)
  }

  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const detail = payload?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : `The backend returned an error (HTTP ${response.status}).`
    throw new Error(message)
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
