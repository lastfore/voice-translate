import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { PathInput } from '@/components/forms/PathInput'
import { StageParamForm } from '@/components/forms/StageParamForm'
import { ArtifactAudio } from '@/components/pipeline/ArtifactAudio'
import { StageLogPanel } from '@/components/pipeline/StageLogPanel'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { useProject } from '@/context/ProjectContext'
import { projectDefaultsKey, useProjectDefaults } from '@/hooks/useProjectDefaults'
import { useStageParams } from '@/hooks/useStageParams'
import { useStageRun } from '@/hooks/useStageRun'
import type { StageParamValues } from '@/types/pipeline'

function SeparatePageInner({ projectId }: { projectId: string }) {
  const { data: defaults, isLoading: defaultsLoading } = useProjectDefaults(projectId)
  const { data: schema, isLoading: schemaLoading } = useStageParams({ stage: 'separate' })
  const stageRun = useStageRun(projectId, 'separate')
  const queryClient = useQueryClient()
  const [mixOverride, setMixOverride] = useState('')

  useEffect(() => {
    if (stageRun.status === 'done') {
      toast.success('分离完成')
      queryClient.invalidateQueries({ queryKey: projectDefaultsKey(projectId) })
    } else if (stageRun.status === 'failed' || stageRun.status === 'error') {
      toast.error(stageRun.errorMessage ?? '分离运行失败')
    }
    // Only fire on status transitions, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stageRun.status])

  const handleSubmit = (values: StageParamValues) => {
    const params: StageParamValues = { ...values }
    if (mixOverride.trim()) params.mix_audio = mixOverride.trim()
    stageRun.run(params)
  }

  if (defaultsLoading || schemaLoading || !defaults || !schema) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2" data-testid="separate-page">
      <Card>
        <CardHeader>
          <CardTitle>分离参数</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <PathInput
            label="混音文件路径（留空则使用项目默认输入）"
            value={mixOverride}
            onChange={setMixOverride}
            extensions={['.flac', '.wav', '.mp3', '.m4a', '.ogg']}
            helpText={defaults.mix_audio ? `当前默认：${defaults.mix_audio}` : '尚未解析到默认混音文件'}
          />
          <StageParamForm
            params={schema.params}
            defaultValues={defaults.stage_params.separate}
            onSubmit={handleSubmit}
            submitLabel="运行分离"
            isSubmitting={stageRun.status === 'running'}
            extraFooter={
              stageRun.status === 'running' ? (
                <Button type="button" variant="outline" onClick={stageRun.cancel} data-testid="separate-cancel">
                  取消
                </Button>
              ) : null
            }
          />
          <Separator />
          <StageLogPanel status={stageRun.status} logs={stageRun.logs} errorMessage={stageRun.errorMessage} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>产物预览</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <ArtifactAudio label="人声 (vocals)" src={defaults.artifacts.sep_vocals} />
          <ArtifactAudio label="伴奏 (instrumental)" src={defaults.artifacts.sep_instrumental} />
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * Separate ("分离") tab — migrated from the corresponding Tab in
 * webui/pipeline_app.py + webui/components/{path_input,stage_params,artifacts}.py.
 *
 * `key={projectId}` forces `SeparatePageInner` (and everything inside it,
 * including the `StageParamForm`) to remount when the active project
 * changes, so `defaultValues` are re-read from the new project's `defaults`
 * exactly once — no `useEffect(() => form.reset(...), [defaults])` anywhere
 * (migration doc §6.2, mandatory).
 */
export function SeparatePage() {
  const { projectId } = useProject()

  if (!projectId) {
    return <p className="text-sm text-muted-foreground">请先在左侧选择或创建一个项目。</p>
  }

  return <SeparatePageInner key={projectId} projectId={projectId} />
}
