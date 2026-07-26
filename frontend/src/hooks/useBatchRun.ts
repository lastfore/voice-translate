import { useCallback, useEffect, useRef, useState } from 'react'

import { postSse } from '@/lib/sse'
import type { StageLogEvent } from '@/types/pipeline'

export type BatchRunStatus = 'idle' | 'running' | 'done' | 'error'

export interface UseBatchRunResult {
  status: BatchRunStatus
  logs: StageLogEvent[]
  errorMessage: string | null
  run: () => void
  cancel: () => void
}

export function useBatchRun(): UseBatchRunResult {
  const [status, setStatus] = useState<BatchRunStatus>('idle')
  const [logs, setLogs] = useState<StageLogEvent[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const cancel = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  const run = useCallback(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLogs([])
    setErrorMessage(null)
    setStatus('running')

    postSse({
      url: '/api/batch/run',
      body: {},
      signal: controller.signal,
      onMessage: (event) => {
        if (event.type === 'log') {
          setLogs((prev) => [...prev, event.data as StageLogEvent])
        } else if (event.type === 'done') {
          setStatus('done')
        } else if (event.type === 'error') {
          const err = event.data as { message?: string }
          setErrorMessage(err?.message ?? 'batch run failed')
          setStatus('error')
        }
      },
    }).catch((err: unknown) => {
      if (controller.signal.aborted) {
        setStatus('idle')
        return
      }
      setStatus('error')
      setErrorMessage(err instanceof Error ? err.message : String(err))
    })
  }, [])

  return { status, logs, errorMessage, run, cancel }
}
