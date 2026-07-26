import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { PathInput } from '@/components/forms/PathInput'
import { StageParamForm } from '@/components/forms/StageParamForm'
import { SliceTuner } from '@/components/slices/SliceTuner'
import { ArtifactAudio } from '@/components/pipeline/ArtifactAudio'
import { ModeTabs } from '@/components/pipeline/ModeTabs'
import { StageLogPanel } from '@/components/pipeline/StageLogPanel'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { useProject } from '@/context/ProjectContext'
import { projectDefaultsKey, useProjectDefaults } from '@/hooks/useProjectDefaults'
import { useStageParams } from '@/hooks/useStageParams'
import { useStageRun } from '@/hooks/useStageRun'
import { api } from '@/lib/api'
import { CONVERT_BATCH, CONVERT_FULL, CONVERT_TAB_LABELS } from '@/lib/modes'
import type { ConvertMode, StageParamValues } from '@/types/pipeline'

type ConvertTab = 'slice_batch' | 'full_track' | 'slice_tuner'

function ConvertPageInner({ projectId, initialMode }: { projectId: string; initialMode: ConvertMode }) {
  const [tab, setTab] = useState<ConvertTab>(initialMode === 'full_track' ? 'full_track' : 'slice_batch')
  const [sourceOverride, setSourceOverride] = useState('')
  const [referenceOverride, setReferenceOverride] = useState('')
  const [referenceFile, setReferenceFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  const { data: defaults } = useProjectDefaults(projectId)
  const { data: schema, isLoading: schemaLoading } = useStageParams({ stage: 'convert' })
  const stageRun = useStageRun(projectId, 'convert')
  const queryClient = useQueryClient()

  useEffect(() => {
    if (stageRun.status === 'done') {
      toast.success('转换完成')
      queryClient.invalidateQueries({ queryKey: projectDefaultsKey(projectId) })
    } else if (stageRun.status === 'failed' || stageRun.status === 'error') {
      toast.error(stageRun.errorMessage ?? '转换运行失败')
    }
  }, [stageRun.status, stageRun.errorMessage, projectId, queryClient])

  const mode: ConvertMode = tab === 'full_track' ? 'full_track' : 'slice_batch'

  useEffect(() => {
    const activeSliceMode = defaults?.active_slice_mode ?? 'lrc'
    api
      .get<{ url: string | null }>(`/api/projects/${projectId}/artifacts/convert-preview`, {
        mode,
        slice_mode: activeSliceMode,
      })
      .then((resp) => setPreviewUrl(resp.url))
      .catch(() => setPreviewUrl(null))
  }, [projectId, mode, defaults?.active_slice_mode, stageRun.status])

  const visibleParams = (schema?.params ?? []).filter((p) => {
    if (mode === CONVERT_FULL && p.slice_batch_only) return false
    if (mode === CONVERT_BATCH && p.full_track_only) return false
    return true
  })

  const handleSubmit = async (values: StageParamValues) => {
    const params: StageParamValues = { ...values, mode }
    if (sourceOverride.trim()) {
      if (mode === CONVERT_FULL) {
        params.source_vocals = sourceOverride.trim()
      } else {
        params.slices_dir = sourceOverride.trim()
      }
    }

    let referencePath = referenceOverride.trim()
    if (referenceFile) {
      const form = new FormData()
      form.set('audio', referenceFile)
      try {
        const resp = await api.post<{ reference: string }>(`/api/projects/${projectId}/reference`, form)
        referencePath = resp.reference
        setReferenceOverride(referencePath)
        setReferenceFile(null)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '参考音频上传失败')
        return
      }
    }
    if (referencePath) {
      params.reference = referencePath
    }

    params.active_slice_mode = defaults?.active_slice_mode ?? 'lrc'
    params.slice_mode = defaults?.active_slice_mode ?? 'lrc'
    stageRun.run(params)
  }

  const sourceLabel = mode === CONVERT_FULL ? '源人声音轨' : '切片目录'
  const sourceHelp =
    mode === CONVERT_FULL
      ? defaults?.vocals_path
        ? `当前默认：${defaults.vocals_path}`
        : '尚未解析到源人声文件'
      : defaults?.slices_dir
        ? `当前默认：${defaults.slices_dir}`
        : '尚未解析到切片目录'

  return (
    <div className="space-y-4" data-testid="convert-page">
      <ModeTabs
        value={tab}
        onChange={(v) => setTab(v as ConvertTab)}
        options={[
          { value: 'slice_batch', label: CONVERT_TAB_LABELS['slice_batch'] },
          { value: 'full_track', label: CONVERT_TAB_LABELS['full_track'] },
          { value: 'slice_tuner', label: '精修' },
        ]}
      />

      {tab === 'slice_tuner' ? (
        <SliceTuner projectId={projectId} sliceMode={defaults?.active_slice_mode ?? 'lrc'} />
      ) : (
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>转换参数（{CONVERT_TAB_LABELS[mode]}）</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <PathInput
              label={sourceLabel}
              value={sourceOverride}
              onChange={setSourceOverride}
              directory={mode === CONVERT_BATCH}
              extensions={mode === CONVERT_FULL ? ['.flac', '.wav', '.mp3'] : undefined}
              helpText={sourceHelp}
            />
            <div className="space-y-1.5">
              <Label>参考音频</Label>
              <div className="flex gap-2">
                <Input
                  value={referenceOverride}
                  onChange={(e) => setReferenceOverride(e.target.value)}
                  placeholder="可手动输入路径，或上传文件"
                  data-testid="convert-reference-path"
                />
                <Input
                  type="file"
                  accept="audio/*"
                  onChange={(e) => setReferenceFile(e.target.files?.[0] ?? null)}
                  data-testid="convert-reference-upload"
                  className="w-auto"
                />
              </div>
              {defaults?.reference && (
                <p className="text-xs text-muted-foreground">当前默认：{defaults.reference}</p>
              )}
            </div>
            {schemaLoading || !schema ? (
              <Skeleton className="h-32 w-full" />
            ) : (
              <StageParamForm
                key={`${projectId}-${mode}`}
                params={visibleParams}
                defaultValues={defaults?.stage_params.convert ?? {}}
                onSubmit={handleSubmit}
                submitLabel="运行转换"
                isSubmitting={stageRun.status === 'running'}
                extraFooter={
                  stageRun.status === 'running' ? (
                    <Button type="button" variant="outline" onClick={stageRun.cancel} data-testid="convert-cancel">
                      取消
                    </Button>
                  ) : null
                }
              />
            )}
            <Separator />
            <StageLogPanel status={stageRun.status} logs={stageRun.logs} errorMessage={stageRun.errorMessage} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>产物预览</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <ArtifactAudio label={mode === CONVERT_FULL ? '整轨转换' : '切片预览'} src={previewUrl} />
          </CardContent>
        </Card>
      </div>
      )}
    </div>
  )
}

/**
 * Convert ("转换") tab — migrated from the corresponding Tab in
 * webui/pipeline_app.py + webui/components/{mode_panel,stage_params,artifacts}.py.
 */
export function ConvertPage() {
  const { projectId } = useProject()
  const { data: defaults, isLoading } = useProjectDefaults(projectId)

  if (!projectId) {
    return <p className="text-sm text-muted-foreground">请先在左侧选择或创建一个项目。</p>
  }

  if (isLoading || !defaults) {
    return <Skeleton className="h-64 w-full" />
  }

  return <ConvertPageInner key={projectId} projectId={projectId} initialMode={defaults.convert_mode} />
}
