import { useCallback, useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { StageParamForm } from '@/components/forms/StageParamForm'
import { ArtifactAudio } from '@/components/pipeline/ArtifactAudio'
import { StageLogPanel } from '@/components/pipeline/StageLogPanel'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { projectDefaultsKey, useProjectDefaults } from '@/hooks/useProjectDefaults'
import { useSliceTable } from '@/hooks/useSliceTable'
import { useStageParams } from '@/hooks/useStageParams'
import { useStageRun } from '@/hooks/useStageRun'
import { api } from '@/lib/api'
import { CONVERT_BATCH } from '@/lib/modes'
import type { SliceMode, SliceRow, StageParamValues } from '@/types/pipeline'

const TUNE_KEYS = [
  'diffusion_steps',
  'length_adjust',
  'inference_cfg_rate',
  'auto_f0_adjust',
  'semi_tone_shift',
  'fp16',
]

interface OverridesResponse {
  slice_mode: SliceMode
  global_defaults: Record<string, unknown>
  slices: Record<string, Record<string, unknown>>
  orphans: Array<Record<string, unknown>>
}

export interface SliceTunerProps {
  projectId: string
  sliceMode: SliceMode
}

export function SliceTuner({ projectId, sliceMode }: SliceTunerProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [firstSelectedId, setFirstSelectedId] = useState<string | null>(null)
  const [referenceFile, setReferenceFile] = useState<File | null>(null)
  const [referencePath, setReferencePath] = useState('')
  const [orphansText, setOrphansText] = useState('')
  const [overrides, setOverrides] = useState<OverridesResponse | null>(null)
  const [lastParams, setLastParams] = useState<StageParamValues | null>(null)

  const { data: defaults } = useProjectDefaults(projectId)
  const { data: schema, isLoading: schemaLoading } = useStageParams({ stage: 'convert', keys: TUNE_KEYS })
  const { data: sliceTable } = useSliceTable(projectId, sliceMode)
  const stageRun = useStageRun(projectId, 'convert')
  const queryClient = useQueryClient()

    const loadOverrides = useCallback(async () => {
    try {
      const resp = await api.get<OverridesResponse>(`/api/projects/${projectId}/slices/overrides`, { mode: sliceMode })
      setOverrides(resp)
      const orphanText = resp.orphans.length
        ? JSON.stringify(resp.orphans, null, 2)
        : '无 orphans'
      setOrphansText(orphanText)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '读取 overrides 失败')
    }
  }, [projectId, sliceMode])

  useEffect(() => {
    loadOverrides()
  }, [loadOverrides])

  useEffect(() => {
    if (stageRun.status === 'done') {
      toast.success('精修重转完成')
      queryClient.invalidateQueries({ queryKey: projectDefaultsKey(projectId) })
      loadOverrides()
    } else if (stageRun.status === 'failed' || stageRun.status === 'error') {
      toast.error(stageRun.errorMessage ?? '精修运行失败')
    }
  }, [stageRun.status, stageRun.errorMessage, projectId, queryClient, loadOverrides])

  const selectedFirstRow = sliceTable?.rows.find((row) => row.id === firstSelectedId) ?? null
  const sourceUrl = selectedFirstRow?.audio_url ?? null
  const convertedUrl = firstSelectedId
    ? `/api/projects/${projectId}/slices/${firstSelectedId}/audio/converted?mode=${sliceMode}`
    : null

  const visibleParams = (schema?.params ?? []).filter((p) => TUNE_KEYS.includes(p.key))
  const defaultValues = overrides?.global_defaults ?? defaults?.stage_params.convert ?? {}

  const handleSelectionChange = (sliceId: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = checked ? [...prev, sliceId] : prev.filter((id) => id !== sliceId)
      if (next.length > 0 && !next.includes(firstSelectedId ?? '')) {
        setFirstSelectedId(next[0])
      } else if (next.length === 0) {
        setFirstSelectedId(null)
      }
      return next
    })
  }

  const handleSave = async (values: StageParamValues) => {
    if (selectedIds.length === 0) {
      toast.error('请选择至少一个切片')
      return
    }
    const params = { ...values }
    if (referenceFile) {
      const form = new FormData()
      form.set('audio', referenceFile)
      try {
        const resp = await api.post<{ reference: string }>(`/api/projects/${projectId}/reference`, form)
        params.reference = resp.reference
        setReferencePath(resp.reference)
        setReferenceFile(null)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '参考音频上传失败')
        return
      }
    } else if (referencePath.trim()) {
      params.reference = referencePath.trim()
    }
    try {
      await api.put(`/api/projects/${projectId}/slices/overrides?mode=${sliceMode}`, {
        slice_ids: selectedIds,
        params,
      })
      setLastParams(params)
      toast.success(`已保存 ${selectedIds.length} 个切片的覆盖参数`)
      loadOverrides()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '保存 overrides 失败')
    }
  }

  const handleRetune = () => {
    if (selectedIds.length === 0) {
      toast.error('请选择至少一个切片')
      return
    }
    if (lastParams === null) {
      toast.error('请先保存覆盖参数')
      return
    }
    const params: StageParamValues = {
      ...lastParams,
      mode: CONVERT_BATCH,
      slice_mode: sliceMode,
      active_slice_mode: sliceMode,
      slice_ids: selectedIds,
      skip_existing: false,
    }
    stageRun.run(params)
  }

  const handleClear = async () => {
    if (selectedIds.length === 0) {
      toast.error('请选择要清除的切片')
      return
    }
    try {
      await api.delete(`/api/projects/${projectId}/slices/overrides?mode=${sliceMode}`, { slice_ids: selectedIds })
      toast.success('已清除选中切片的覆盖参数')
      loadOverrides()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '清除 overrides 失败')
    }
  }

  const handleClearOrphans = async () => {
    try {
      await api.post(`/api/projects/${projectId}/slices/overrides/clear-orphans?mode=${sliceMode}`)
      toast.success('已清除 orphans')
      loadOverrides()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '清除 orphans 失败')
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2" data-testid="slice-tuner">
      <Card>
        <CardHeader>
          <CardTitle>切片精修</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground">当前模式：{sliceMode.toUpperCase()}</p>
          <ScrollArea className="h-48 rounded-md border">
            <div className="space-y-1 p-2">
              {sliceTable?.rows.map((row: SliceRow) => (
                <label
                  key={row.id}
                  className="flex items-center gap-2 rounded px-2 py-1 hover:bg-accent"
                  onClick={() => setFirstSelectedId(row.id)}
                >
                  <Checkbox
                    checked={selectedIds.includes(row.id)}
                    onCheckedChange={(checked) => handleSelectionChange(row.id, checked === true)}
                    data-testid={`slice-tuner-check-${row.id}`}
                  />
                  <span className="text-sm">
                    {row.id} | {row.start_ms}-{row.end_ms}ms {row.text}
                    {overrides?.slices[row.id] ? ' [精修]' : ''}
                  </span>
                </label>
              ))}
              {(sliceTable?.rows.length ?? 0) === 0 && (
                <p className="p-2 text-sm text-muted-foreground">暂无切片数据</p>
              )}
            </div>
          </ScrollArea>

          <div className="grid grid-cols-2 gap-4">
            <ArtifactAudio label="原始切片" src={sourceUrl} />
            <ArtifactAudio label="转换结果" src={convertedUrl} />
          </div>

          <div className="space-y-1.5">
            <Label>参考音频（可覆盖项目默认）</Label>
            <div className="flex gap-2">
              <Input
                value={referencePath}
                onChange={(e) => setReferencePath(e.target.value)}
                placeholder="可手动输入路径，或上传文件"
              />
              <Input
                type="file"
                accept="audio/*"
                onChange={(e) => setReferenceFile(e.target.files?.[0] ?? null)}
                className="w-auto"
              />
            </div>
          </div>

          {schemaLoading || !schema ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <StageParamForm
              params={visibleParams}
              defaultValues={defaultValues}
              onSubmit={handleSave}
              submitLabel="保存为覆盖"
              isSubmitting={false}
            />
          )}

          <div className="flex flex-wrap gap-2">
            <Button onClick={handleRetune} disabled={stageRun.status === 'running'} data-testid="slice-tuner-retune">
              重转选中片
            </Button>
            <Button variant="outline" onClick={handleClear} data-testid="slice-tuner-clear">
              清除选中覆盖
            </Button>
            <Button variant="outline" onClick={handleClearOrphans} data-testid="slice-tuner-clear-orphans">
              清除 orphans
            </Button>
          </div>

          <Separator />
          <StageLogPanel status={stageRun.status} logs={stageRun.logs} errorMessage={stageRun.errorMessage} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>未匹配 overrides (orphans)</CardTitle>
        </CardHeader>
        <CardContent>
          <Textarea value={orphansText} readOnly rows={8} data-testid="slice-tuner-orphans" />
        </CardContent>
      </Card>
    </div>
  )
}
