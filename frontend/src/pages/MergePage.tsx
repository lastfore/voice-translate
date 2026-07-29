import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { PathInput } from '@/components/forms/PathInput'
import { StageParamForm } from '@/components/forms/StageParamForm'
import { ArtifactAudio } from '@/components/pipeline/ArtifactAudio'
import { ModeTabs } from '@/components/pipeline/ModeTabs'
import { StageLogPanel } from '@/components/pipeline/StageLogPanel'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { useProject } from '@/context/ProjectContext'
import { projectDefaultsKey, useProjectDefaults } from '@/hooks/useProjectDefaults'
import { useStageParams } from '@/hooks/useStageParams'
import { useStageRun } from '@/hooks/useStageRun'
import { api } from '@/lib/api'
import { mediaUrlFromPath, withMediaCacheBuster } from '@/lib/media'
import { MERGE_MODES, MERGE_SLICE, MERGE_WHOLE, MERGE_TAB_LABELS } from '@/lib/modes'
import type { MergeMode, StageParamValues } from '@/types/pipeline'

function MergePageInner({ projectId, initialMode }: { projectId: string; initialMode: MergeMode }) {
  const [mode, setMode] = useState<MergeMode>(initialMode)
  const [vocalsOverride, setVocalsOverride] = useState('')
  const [instrumentalOverride, setInstrumentalOverride] = useState('')
  const [referenceOverride, setReferenceOverride] = useState('')
  const [manifestPreview, setManifestPreview] = useState('')
  const [mixedRevision, setMixedRevision] = useState(0)

  const { data: defaults } = useProjectDefaults(projectId)
  const { data: schema, isLoading: schemaLoading } = useStageParams({ stage: 'merge' })
  const stageRun = useStageRun(projectId, 'merge')
  const queryClient = useQueryClient()

  useEffect(() => {
    if (stageRun.status === 'done') {
      toast.success('合并完成')
      setMixedRevision((revision) => revision + 1)
      queryClient.invalidateQueries({ queryKey: projectDefaultsKey(projectId) })
    } else if (stageRun.status === 'failed' || stageRun.status === 'error') {
      toast.error(stageRun.errorMessage ?? '合并运行失败')
    }
  }, [stageRun.status, stageRun.errorMessage, projectId, queryClient])

  const mixedPreviewSrc = useMemo(() => {
    const fromRun = mediaUrlFromPath(stageRun.result?.artifacts?.mixed as string | undefined)
    const fromDefaults = defaults?.artifacts.mixed ?? null
    const base = fromRun ?? fromDefaults
    return base ? withMediaCacheBuster(base, mixedRevision) : null
  }, [defaults?.artifacts.mixed, mixedRevision, stageRun.result])

  useEffect(() => {
    const activeSliceMode = defaults?.active_slice_mode ?? 'lrc'
    api
      .get<{ preview: string }>(`/api/projects/${projectId}/manifest-preview`, {
        mode: activeSliceMode,
      })
      .then((resp) => setManifestPreview(resp.preview))
      .catch(() => setManifestPreview(''))
  }, [projectId, defaults?.active_slice_mode, stageRun.status])

  const handleSubmit = (values: StageParamValues) => {
    const params: StageParamValues = { ...values, merge_mode: mode }
    if (mode === MERGE_WHOLE) {
      if (vocalsOverride.trim()) params.vocals = vocalsOverride.trim()
    } else {
      if (vocalsOverride.trim()) params.vocals = vocalsOverride.trim()
    }
    if (instrumentalOverride.trim()) params.instrumental = instrumentalOverride.trim()
    if (referenceOverride.trim()) params.reference = referenceOverride.trim()
    params.profile = values.profile ?? defaults?.merge_profile ?? 'full'
    if (mode === MERGE_SLICE) {
      const vocalsPath = vocalsOverride.trim() || defaults?.merge_vocals_dir || ''
      const inferredFromVocals = vocalsPath
        ? vocalsPath.replace(/\\/g, '/').match(/\/(lrc|vad)\/?(?:\/|$)/i)?.[1]?.toLowerCase()
        : null
      const sliceMode = inferredFromVocals ?? defaults?.active_slice_mode ?? 'lrc'
      params.slice_mode = sliceMode
      params.active_slice_mode = sliceMode
    }
    stageRun.run(params)
  }

  return (
    <div className="space-y-4" data-testid="merge-page">
      <ModeTabs
        value={mode}
        onChange={setMode}
        options={MERGE_MODES.map((m) => ({ value: m, label: MERGE_TAB_LABELS[m] }))}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>合并参数（{MERGE_TAB_LABELS[mode]}）</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <PathInput
              label={mode === MERGE_WHOLE ? '人声音轨' : '转换后人声目录'}
              value={vocalsOverride}
              onChange={setVocalsOverride}
              directory={mode === MERGE_SLICE}
              extensions={mode === MERGE_WHOLE ? ['.flac', '.wav', '.mp3'] : undefined}
              helpText={
                mode === MERGE_WHOLE
                  ? defaults?.merge_vocals_file
                    ? `当前默认：${defaults.merge_vocals_file}`
                    : '尚未解析到人声音轨'
                  : defaults?.merge_vocals_dir
                    ? `当前默认：${defaults.merge_vocals_dir}`
                    : '尚未解析到转换后人声目录'
              }
            />
            <PathInput
              label="伴奏轨"
              value={instrumentalOverride}
              onChange={setInstrumentalOverride}
              extensions={['.flac', '.wav', '.mp3']}
              helpText={
                defaults?.merge_instrumental
                  ? `当前默认：${defaults.merge_instrumental}`
                  : '尚未解析到伴奏轨'
              }
            />
            <PathInput
              label="参考音频（可选）"
              value={referenceOverride}
              onChange={setReferenceOverride}
              extensions={['.flac', '.wav', '.mp3']}
              helpText={
                defaults?.merge_reference ? `当前默认：${defaults.merge_reference}` : '使用项目输入作为默认参考'
              }
            />
            {schemaLoading || !schema ? (
              <Skeleton className="h-32 w-full" />
            ) : (
              <StageParamForm
                key={`${projectId}-${mode}`}
                params={schema.params}
                defaultValues={defaults?.stage_params.merge ?? {}}
                onSubmit={handleSubmit}
                submitLabel="运行合并"
                isSubmitting={stageRun.status === 'running'}
                extraFooter={
                  stageRun.status === 'running' ? (
                    <Button type="button" variant="outline" onClick={stageRun.cancel} data-testid="merge-cancel">
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
            {manifestPreview && (
              <div className="space-y-1.5">
                <p className="text-sm font-medium">切片清单</p>
                <Textarea value={manifestPreview} readOnly rows={6} data-testid="merge-manifest-preview" />
              </div>
            )}
            <ArtifactAudio
              label="合并结果 (mixed)"
              src={mixedPreviewSrc}
              reloadKey={mixedRevision}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

/**
 * Merge ("合并") tab — migrated from the corresponding Tab in
 * webui/pipeline_app.py + webui/components/{mode_panel,stage_params,artifacts}.py.
 */
export function MergePage() {
  const { projectId } = useProject()
  const { data: defaults, isLoading } = useProjectDefaults(projectId)

  if (!projectId) {
    return <p className="text-sm text-muted-foreground">请先在左侧选择或创建一个项目。</p>
  }

  if (isLoading || !defaults) {
    return <Skeleton className="h-64 w-full" />
  }

  return <MergePageInner key={projectId} projectId={projectId} initialMode={defaults.merge_mode} />
}
