/**
 * API client for the xiaozhi-bridge backend.
 *
 * Talks to the bridge HTTP API (V2; for V1 most data is just WebSocket).
 * All requests go through the Vite dev proxy in development.
 */

const BASE = '/api'

export interface Device {
  id: string
  name: string
  mac: string
  // V2 #6: user-friendly metadata, edited from the Devices page
  // detail modal. Backend stores NULL for legacy rows and the
  // API surfaces them as ''; we keep them as optional so an
  // older backend (v0.2.0~v0.2.5) doesn't break the UI.
  notes?: string
  room?: string
  state: 'idle' | 'listening' | 'thinking' | 'speaking' | 'offline'
  lastSeen: string
  sessionId?: string
}

export interface DevicePatch {
  // All fields optional; backend only touches what's sent.
  name?: string
  notes?: string
  room?: string
}

export interface Conversation {
  id: string
  deviceId: string
  sessionId?: string
  startedAt: string
  endedAt?: string
  turns: ConversationTurn[]
  llmStatus?: 'ok' | 'error' | 'fallback'
}

export interface ConversationTurn {
  role: 'user' | 'assistant'
  text: string
  timestamp: string
  toolCalls?: Array<{ name: string; arguments: Record<string, unknown> }>
}

export interface IotDevice {
  id: string
  name: string
  type: 'light' | 'switch' | 'fan' | 'ac' | 'curtain' | 'sensor' | 'other'
  room?: string
  state: Record<string, unknown>
  online: boolean
}

class APIError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new APIError(resp.status, text || resp.statusText)
  }
  return resp.json() as Promise<T>
}

export const api = {
  // --- Devices ---
  listDevices: () => request<Device[]>('/devices'),
  getDevice: (id: string) => request<Device>(`/devices/${id}`),
  // V2 #6: partial-update metadata. Empty object {} would 422
  // server-side; the caller is expected to pass at least one
  // field (the modal disables Save when all fields are empty).
  patchDevice: (id: string, patch: DevicePatch) =>
    request<Device>(`/devices/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  // V2 #6: delete the device and cascade its conversations to
  // the 'unknown' bucket. The detail modal shows a confirm
  // dialog before calling this.
  deleteDevice: (id: string) =>
    request<{ deleted: string }>(`/devices/${id}`, {
      method: 'DELETE',
    }),
  rebootDevice: (id: string) => request<void>(`/devices/${id}/reboot`, { method: 'POST' }),

  // --- Conversations ---
  listConversations: (params?: { deviceId?: string; limit?: number }) => {
    const search = new URLSearchParams()
    if (params?.deviceId) search.set('deviceId', params.deviceId)
    if (params?.limit) search.set('limit', String(params.limit))
    const q = search.toString()
    return request<Conversation[]>(`/conversations${q ? `?${q}` : ''}`)
  },
  getConversation: (id: string) => request<Conversation>(`/conversations/${id}`),

  // --- IoT ---
  listIotDevices: () => request<IotDevice[]>('/iot'),
  controlIot: (id: string, body: { action: 'on' | 'off'; value?: unknown }) =>
    request<IotDevice>(`/iot/${id}/control`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // --- Settings ---
  getConfig: () => request<Record<string, unknown>>('/config'),
  updateConfig: (patch: Record<string, unknown>) =>
    request<Record<string, unknown>>('/config', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  // --- Logs (SSE) ---
  streamLogs(onEvent: (line: string) => void): EventSource {
    // Note: actual parsing of SSE happens in the consumer
    const source = new EventSource(`${BASE}/logs/stream`)
    source.addEventListener('message', (e) => onEvent((e as MessageEvent).data))
    return source
  },
}

export { APIError }
