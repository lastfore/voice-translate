/**
 * SSE transport — migration doc §4.1.2.
 *
 * Native `EventSource` only supports GET and can't carry a request body, so
 * every SSE endpoint in this app is POST + JSON body, consumed via
 * `fetch()` + `ReadableStream` parsing. Do not reach for `EventSource` here.
 */

export interface SseMessage {
  type: string
  data: unknown
}

export interface SseOptions {
  url: string
  body?: unknown
  method?: 'GET' | 'POST'
  signal?: AbortSignal
  onMessage: (event: SseMessage) => void
  onError?: (err: Error) => void
}

export async function postSse(opts: SseOptions): Promise<void> {
  return streamSse({ ...opts, method: 'POST' })
}

export async function getSse(opts: Omit<SseOptions, 'method' | 'body'>): Promise<void> {
  return streamSse({ ...opts, method: 'GET' })
}

export async function streamSse(opts: SseOptions): Promise<void> {
  const init: RequestInit = {
    method: opts.method ?? 'POST',
    headers: { Accept: 'text/event-stream' },
    signal: opts.signal,
  }
  if (opts.method !== 'GET' && opts.body !== undefined) {
    init.headers = { ...(init.headers as Record<string, string>), 'Content-Type': 'application/json' }
    init.body = JSON.stringify(opts.body)
  }
  const resp = await fetch(opts.url, init)
  if (!resp.ok || !resp.body) {
    throw new Error(`SSE ${resp.status}`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      if (!frame.trim()) continue
      const type = /^event: (.+)$/m.exec(frame)?.[1] ?? 'message'
      const data = /^data: (.+)$/m.exec(frame)?.[1] ?? ''
      try {
        opts.onMessage({ type, data: JSON.parse(data) })
      } catch {
        opts.onMessage({ type, data })
      }
    }
  }
}
