import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { PathInput } from '@/components/forms/PathInput'
import { StageParamForm } from '@/components/forms/StageParamForm'
import { ArtifactAudio } from '@/components/pipeline/ArtifactAudio'
import { ModeTabs } from '@/components/pipeline/ModeTabs'
import { StageLogPanel } from '@/components/pipeline/StageLogPanel'
import { SliceTable } from '@/components/slices/SliceTable'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { useProject } from '@/context/ProjectContext'
import { projectDefaultsKey, useProjectDefaults } from '@/hooks/useProjectDefaults'
import { useSliceTable } from '@/hooks/useSliceTable'
import { useStageParams } from '@/hooks/useStageParams'
import { useStageRun } from '@/hooks/useStageRun'
import { SLICE_MODES, SLICE_TAB_LABELS } from '@/lib/modes'
import type { SliceMode, SliceRow, StageParamValues } from '@/types/pipeline'

function SlicePageInner({ projectId, initialMode }: { projectId: string; initialMode: SliceMode }) {
  const [mode, setMode] = useState<SliceMode>(initialMode)
  const [selectedSlice, setSelectedSlice] = useState<SliceRow | null>(null)
  const [vocalsOverride, setVocalsOverride] = useState('')
  const [lrcOverride, setLrcOverride] = useState('')

  const { data: defaults } = useProjectDefaults(projectId)
  const { data: schema, isLoading: schemaLoading } = useStageParams({
    stage: 'slice',
    vadOnly: mode === 'vad',
    lrcOnly: mode === 'lrc',
  })
  const { data: sliceTable, isLoading: slicesLoading } = useSliceTable(projectId, mode)
  const stageRun = useStageRun(projectId, 'slice')
  const queryClient = useQueryClient()

  // Reset the preview selection to the first row whenever the slice list for
  // the active mode changes (e.g. mode switch, or a fresh run) — this is
  // *display* sync, not form state, so it doesn't fall under the
  // "no useEffect + reset" rule in docs §6.2 (that rule is about
  // react-hook-form `defaultValues`, not derived selection state).
  useEffect(() => {
    const first = sliceTable?.rows[0] ?? null
    setSelectedSlice(first)
  }, [sliceTable])

  useEffect(() => {
    if (stageRun.status === 'done') {
      toast.success('切片完成')
      queryClient.invalidateQueries({ queryKey: projectDefaultsKey(projectId) })
      queryClient.invalidateQueries({ queryKey: ['slices', projectId] })
    } else if (stageRun.status === 'failed' || stageRun.status === 'error') {
      toast.error(stageRun.errorMessage ?? '切片运行失败')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stageRun.status])

  const visibleParams = schema?.params ?? []

  const handleSubmit = (values: StageParamValues) => {
    const params: StageParamValues = { ...values, mode }
    params.slice_mode = mode
    params.active_slice_mode = mode
    if (vocalsOverride.trim()) params.vocals = vocalsOverride.trim()
    if (mode === 'lrc' && lrcOverride.trim()) params.lrc = lrcOverride.trim()
    stageRun.run(params)
  }

  return (
    <div className="space-y-4" data-testid="slice-page">
      <ModeTabs
        value={mode}
        onChange={setMode}
        options={SLICE_MODES.map((m) => ({ value: m, label: SLICE_TAB_LABELS[m] }))}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>切片参数（{SLICE_TAB_LABELS[mode]}）</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <PathInput
              label="人声输入路径（留空则使用分离产物）"
              value={vocalsOverride}
              onChange={setVocalsOverride}
              extensions={['.flac', '.wav', '.mp3']}
              helpText={defaults?.vocals_path ? `当前默认：${defaults.vocals_path}` : undefined}
            />
            {mode === 'lrc' && (
              <PathInput
                label="LRC 歌词路径"
                value={lrcOverride}
                onChange={setLrcOverride}
                extensions={['.lrc']}
                helpText={defaults?.lrc_path ? `当前默认：${defaults.lrc_path}` : undefined}
              />
            )}
            {schemaLoading || !schema ? (
              <Skeleton className="h-32 w-full" />
            ) : (
              <StageParamForm
                key={`${projectId}-${mode}`}
                params={visibleParams}
                defaultValues={defaults?.stage_params.slice ?? {}}
                onSubmit={handleSubmit}
                submitLabel="运行切片"
                isSubmitting={stageRun.status === 'running'}
                extraFooter={
                  stageRun.status === 'running' ? (
                    <Button type="button" variant="outline" onClick={stageRun.cancel} data-testid="slice-cancel">
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
            <CardTitle>切片列表</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="truncate rounded bg-muted px-2 py-1 text-xs text-muted-foreground" data-testid="slice-dir-path">
              {sliceTable?.dir_path ? `切片目录：${sliceTable.dir_path}` : '无切片目录'}
            </p>
            {slicesLoading ? (
              <Skeleton className="h-48 w-full" />
            ) : (
              <SliceTable
                rows={sliceTable?.rows ?? []}
                selectedId={selectedSlice?.id ?? null}
                onSelectRow={setSelectedSlice}
              />
            )}
            <ArtifactAudio label="选中切片预览" src={selectedSlice?.audio_url} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

/**
 * Slice ("切片") tab — migrated from webui/components/{mode_panel,slice_preview}.py
 * + the Slice Tab wiring in webui/pipeline_app.py (migration doc §5.10).
 *
 * Same `key={projectId}` remount contract as `SeparatePage` (§6.2): switching
 * projects remounts this whole subtree so `mode`/form state starts fresh
 * from the new project's `defaults`, never from a stale `useEffect` reset.
 */
export function SlicePage() {
  const { projectId } = useProject()
  const { data: defaults, isLoading } = useProjectDefaults(projectId)

  if (!projectId) {
    return <p className="text-sm text-muted-foreground">请先在左侧选择或创建一个项目。</p>
  }

  if (isLoading || !defaults) {
    return <Skeleton className="h-64 w-full" />
  }

  return <SlicePageInner key={projectId} projectId={projectId} initialMode={defaults.active_slice_mode} />
}
