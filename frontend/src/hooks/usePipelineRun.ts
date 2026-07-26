import { useCallback, useEffect, useRef, useState } from 'react'

import { postSse } from '@/lib/sse'
import type { StageDoneEvent, StageLogEvent, StageName, StageParamValues } from '@/types/pipeline'

export type PipelineRunStatus = 'idle' | 'running' | 'done' | 'failed' | 'error'

export interface UsePipelineRunResult {
  status: PipelineRunStatus
  logs: StageLogEvent[]
  result: StageDoneEvent | null
  errorMessage: string | null
  run: (options: { from_stage?: StageName; stages?: StageName[]; params: StageParamValues }) => void
  cancel: () => void
}

export function usePipelineRun(projectId: string | null): UsePipelineRunResult {
  const [status, setStatus] = useState<PipelineRunStatus>('idle')
  const [logs, setLogs] = useState<StageLogEvent[]>([])
  const [result, setResult] = useState<StageDoneEvent | null>(null)
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

  const run = useCallback(
    (options: { from_stage?: StageName; stages?: StageName[]; params: StageParamValues }) => {
      if (!projectId) return
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      setLogs([])
      setResult(null)
      setErrorMessage(null)
      setStatus('running')

      const body: Record<string, unknown> = { params: options.params }
      if (options.stages) {
        body.stages = options.stages
      } else if (options.from_stage) {
        body.from_stage = options.from_stage
      }

      postSse({
        url: `/api/projects/${projectId}/pipeline/run`,
        body,
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
            setErrorMessage(err?.message ?? 'pipeline run failed')
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
    [projectId]
  )

  return { status, logs, result, errorMessage, run, cancel }
}
