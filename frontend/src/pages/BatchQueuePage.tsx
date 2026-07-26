import { useState } from 'react'
import { toast } from 'sonner'

import { StageLogPanel } from '@/components/pipeline/StageLogPanel'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { useProjects } from '@/hooks/useProjects'
import { useBatchRun } from '@/hooks/useBatchRun'
import { useBatchStatus } from '@/hooks/useBatchStatus'
import { api } from '@/lib/api'
import type { StageName } from '@/types/pipeline'

const STAGES: StageName[] = ['separate', 'slice', 'convert', 'merge']

export function BatchQueuePage() {
  const { data: projects, isLoading } = useProjects()
  const { snapshot } = useBatchStatus()
  const batchRun = useBatchRun()
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([])
  const [selectedStages, setSelectedStages] = useState<StageName[]>(['separate'])
  const [convertMode, setConvertMode] = useState('slice_batch')
  const [sliceMode, setSliceMode] = useState('lrc')
  const [mergeProfile, setMergeProfile] = useState('full')

  const handleEnqueue = async () => {
    if (selectedProjectIds.length === 0) {
      toast.error('请选择至少一个项目')
      return
    }
    try {
      for (const projectId of selectedProjectIds) {
        await api.post('/api/batch/enqueue', {
          project_id: projectId,
          stages: selectedStages,
          params: { convert_mode: convertMode, slice_mode: sliceMode, profile: mergeProfile },
        })
      }
      toast.success(`已加入 ${selectedProjectIds.length} 个项目到批量队列`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '入队失败')
    }
  }

  const handleClear = async () => {
    try {
      const resp = await api.post<{ removed: number }>('/api/batch/clear', { remove_done: true, remove_failed: true })
      toast.success(`已清除 ${resp.removed} 项`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '清除失败')
    }
  }

  return (
    <div className="space-y-4" data-testid="batch-queue-page">
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>批量队列</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label>选择项目</Label>
              {isLoading ? (
                <Skeleton className="h-24 w-full" />
              ) : (
                <div className="space-y-1 rounded-md border p-2">
                  {(projects ?? []).map((p) => (
                    <label key={p.id} className="flex items-center gap-2">
                      <Checkbox
                        checked={selectedProjectIds.includes(p.id)}
                        onCheckedChange={(checked) => {
                          setSelectedProjectIds((prev) =>
                            checked ? [...prev, p.id] : prev.filter((id) => id !== p.id)
                          )
                        }}
                        data-testid={`batch-project-${p.id}`}
                      />
                      <span className="text-sm">
                        {p.display_name} ({p.id})
                      </span>
                    </label>
                  ))}
                  {(projects ?? []).length === 0 && (
                    <p className="text-sm text-muted-foreground">暂无项目</p>
                  )}
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <Label>选择阶段</Label>
              <div className="flex flex-wrap gap-2">
                {STAGES.map((stage) => (
                  <label key={stage} className="flex items-center gap-1">
                    <Checkbox
                      checked={selectedStages.includes(stage)}
                      onCheckedChange={(checked) => {
                        setSelectedStages((prev) =>
                          checked ? [...prev, stage] : prev.filter((s) => s !== stage)
                        )
                      }}
                    />
                    <span className="text-sm">{stage}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-1.5">
                <Label>转换模式</Label>
                <Input value={convertMode} onChange={(e) => setConvertMode(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>切片模式</Label>
                <Input value={sliceMode} onChange={(e) => setSliceMode(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>合并 profile</Label>
                <Input value={mergeProfile} onChange={(e) => setMergeProfile(e.target.value)} />
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button onClick={handleEnqueue} data-testid="batch-enqueue">
                加入队列
              </Button>
              <Button onClick={batchRun.run} disabled={batchRun.status === 'running'} data-testid="batch-run">
                执行队列
              </Button>
              <Button variant="outline" onClick={handleClear} data-testid="batch-clear">
                清除已完成
              </Button>
              {batchRun.status === 'running' && (
                <Button variant="outline" onClick={batchRun.cancel}>
                  取消
                </Button>
              )}
            </div>

            <Separator />
            <StageLogPanel status={batchRun.status} logs={batchRun.logs} errorMessage={batchRun.errorMessage} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>队列状态</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-sm text-muted-foreground">
              运行中：{snapshot?.running ? '是' : '否'}
            </p>
            <p className="text-sm text-muted-foreground">队列项：{snapshot?.items.length ?? 0}</p>
            <div className="rounded-md border">
              {(snapshot?.items ?? []).map((item) => (
                <div key={item.id} className="flex items-center justify-between border-b px-3 py-2 text-sm last:border-b-0">
                  <span>
                    {item.project_id} | {item.stages.join(',')}
                  </span>
                  <span className="text-muted-foreground">{item.status}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
