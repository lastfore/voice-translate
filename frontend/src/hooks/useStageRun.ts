import { useCallback, useEffect, useRef, useState } from 'react'

import { postSse } from '@/lib/sse'
import type { StageDoneEvent, StageLogEvent, StageName, StageParamValues } from '@/types/pipeline'

export type StageRunStatus = 'idle' | 'running' | 'done' | 'failed' | 'error'

export interface UseStageRunResult {
  status: StageRunStatus
  logs: StageLogEvent[]
  result: StageDoneEvent | null
  errorMessage: string | null
  run: (params: StageParamValues) => void
  cancel: () => void
}

/**
 * SSE stage-run hook — migration doc §4.1.2 (postSse transport) + §4.1.4
 * (client cancellation). The `AbortController` is aborted automatically on
 * unmount so navigating away from a running page stops the backend job
 * (TC-Phase1-06).
 */
export function useStageRun(projectId: string | null, stage: StageName): UseStageRunResult {
  const [status, setStatus] = useState<StageRunStatus>('idle')
  const [logs, setLogs] = useState<StageLogEvent[]>([])
  const [result, setResult] = useState<StageDoneEvent | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const cancel = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  useEffect(() => {
    // Unmount => abort any in-flight run (docs §4.1.4 "页面卸载触发取消").
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  const run = useCallback(
    (params: StageParamValues) => {
      if (!projectId) return
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      setLogs([])
      setResult(null)
      setErrorMessage(null)
      setStatus('running')

      postSse({
        url: `/api/projects/${projectId}/stages/${stage}/run`,
        body: { params },
        signal: controller.signal,
        onMessage: (event) => {
          if (event.type === 'log') {
            setLogs((prev) => [...prev, event.data as StageLogEvent])
          } else if (event.type === 'done') {
            const done = event.data as StageDoneEvent
            setResult(done)
            setStatus(done.success ? 'done' : 'failed')
            if (!done.success && done.error) setErrorMessage(done.error)
          } else if (event.type === 'error') {
            const err = event.data as { message?: string }
            setErrorMessage(err?.message ?? 'stage run failed')
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
    },
    [projectId, stage]
  )

  return { status, logs, result, errorMessage, run, cancel }
}
