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
  state: 'idle' | 'listening' | 'thinking' | 'speaking' | 'offline'
  lastSeen: string
  sessionId?: string
}

export interface Conversation {
  id: string
  deviceId: string
  startedAt: string
  endedAt?: string
  turns: ConversationTurn[]
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
  controlIot: (id: string, action: string, value?: unknown) =>
    request<IotDevice>(`/iot/${id}/control`, {
      method: 'POST',
      body: JSON.stringify({ action, value }),
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
    return new EventSource(`${BASE}/logs/stream`)
      // Note: actual parsing of SSE happens in the consumer
      .addEventListener('message', (e) => onEvent((e as MessageEvent).data))
  },
}

export { APIError }
