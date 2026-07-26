import { useEffect, useRef } from 'react'

import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { StageLogEvent } from '@/types/pipeline'
import type { StageRunStatus } from '@/hooks/useStageRun'

interface StageLogPanelProps {
  status: StageRunStatus
  logs: StageLogEvent[]
  errorMessage?: string | null
}

const STATUS_LABEL: Record<StageRunStatus, string> = {
  idle: '空闲',
  running: '运行中',
  done: '完成',
  failed: '失败',
  error: '错误',
}

const STATUS_VARIANT: Record<StageRunStatus, 'secondary' | 'success' | 'destructive' | 'warning'> = {
  idle: 'secondary',
  running: 'warning',
  done: 'success',
  failed: 'destructive',
  error: 'destructive',
}

const MAX_LOG_LINES = 80

/** SSE log accumulation panel — migrated from the Gradio log Textbox. Truncates to the last 80 lines to match the old UI behavior. */
export function StageLogPanel({ status, logs, errorMessage }: StageLogPanelProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const visible = logs.length > MAX_LOG_LINES ? logs.slice(-MAX_LOG_LINES) : logs
  const truncated = logs.length - visible.length

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [logs.length])

  return (
    <div className="space-y-2" data-testid="stage-log-panel">
      <div className="flex items-center gap-2">
        <Badge variant={STATUS_VARIANT[status]} data-testid="stage-run-status">
          {STATUS_LABEL[status]}
        </Badge>
        {errorMessage && <span className="text-xs text-destructive">{errorMessage}</span>}
      </div>
      <ScrollArea className="h-40 rounded-md border bg-muted/30 p-2">
        <div className="space-y-1 font-mono text-xs">
          {logs.length === 0 && <p className="text-muted-foreground">暂无日志</p>}
          {truncated > 0 && (
            <p className="text-muted-foreground" data-testid="stage-log-truncated">
              … 已隐藏 {truncated} 条早期日志，仅保留最近 {MAX_LOG_LINES} 条
            </p>
          )}
          {visible.map((log, idx) => (
            <p key={idx} data-testid="stage-log-line">
              [{log.percent.toFixed(0)}%] {log.log_line ?? log.message}
            </p>
          ))}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
    </div>
  )
}
