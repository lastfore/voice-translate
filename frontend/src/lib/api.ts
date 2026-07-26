/**
 * Thin fetch wrapper for the FastAPI backend (migration doc §8 "数据请求").
 *
 * All calls go through the Vite dev proxy (`/api` -> `http://127.0.0.1:8000`,
 * see vite.config.ts) so relative paths work in both dev and a same-origin
 * production build.
 */

export class ApiError extends Error {
  status: number
  body: unknown

  constructor(status: number, message: string, body: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

async function parseErrorBody(resp: Response): Promise<{ message: string; body: unknown }> {
  const text = await resp.text()
  if (!text) {
    return { message: resp.statusText || `HTTP ${resp.status}`, body: null }
  }
  try {
    const json = JSON.parse(text)
    const message = typeof json?.detail === 'string' ? json.detail : JSON.stringify(json.detail ?? json)
    return { message, body: json }
  } catch {
    return { message: text, body: text }
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init)
  if (!resp.ok) {
    const { message, body } = await parseErrorBody(resp)
    throw new ApiError(resp.status, message, body)
  }
  if (resp.status === 204) {
    return undefined as T
  }
  const contentType = resp.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    return undefined as T
  }
  return (await resp.json()) as T
}

export const api = {
  get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
    const url = new URL(path, window.location.origin)
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined) url.searchParams.set(key, String(value))
      }
    }
    return request<T>(url.pathname + '?' + url.searchParams.toString())
  },

  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  },

  postForm<T>(path: string, formData: FormData): Promise<T> {
    return request<T>(path, { method: 'POST', body: formData })
  },

  delete<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  },

  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  },
}
