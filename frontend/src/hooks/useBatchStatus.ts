import { useEffect, useRef, useState } from 'react'

import { getSse } from '@/lib/sse'

export interface BatchItem {
  id: string
  project_id: string
  stages: string[]
  params: Record<string, unknown>
  status: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface BatchSnapshot {
  running: boolean
  items: BatchItem[]
}

export interface UseBatchStatusResult {
  snapshot: BatchSnapshot | null
  error: string | null
}

export function useBatchStatus(): UseBatchStatusResult {
  const [snapshot, setSnapshot] = useState<BatchSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    getSse({
      url: '/api/batch/status',
      signal: controller.signal,
      onMessage: (event) => {
        if (event.type === 'status') {
          setSnapshot(event.data as BatchSnapshot)
        } else if (event.type === 'error') {
          const err = event.data as { message?: string }
          setError(err?.message ?? 'batch status failed')
        }
      },
    }).catch((err: unknown) => {
      if (controller.signal.aborted) return
      setError(err instanceof Error ? err.message : String(err))
    })

    return () => {
      controller.abort()
    }
  }, [])

  return { snapshot, error }
}
