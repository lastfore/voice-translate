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

function DeharmonizePageInner({ projectId }: { projectId: string }) {
  const { data: defaults, isLoading: defaultsLoading } = useProjectDefaults(projectId)
  const { data: schema, isLoading: schemaLoading } = useStageParams({ stage: 'deharmonize' })
  const stageRun = useStageRun(projectId, 'deharmonize')
  const queryClient = useQueryClient()
  const [vocalsOverride, setVocalsOverride] = useState('')

  useEffect(() => {
    if (stageRun.status === 'done') {
      const arts = stageRun.result?.artifacts ?? {}
      const skipped = !arts.lead_vocals && !!arts.meta
      if (skipped) {
        toast.info('和声能量过低，已跳过和声剥离')
      } else {
        toast.success('和声剥离完成')
      }
      queryClient.invalidateQueries({ queryKey: projectDefaultsKey(projectId) })
    } else if (stageRun.status === 'failed' || stageRun.status === 'error') {
      toast.error(stageRun.errorMessage ?? '和声剥离运行失败')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stageRun.status])

  const handleSubmit = (values: StageParamValues) => {
    const params: StageParamValues = { ...values }
    if (vocalsOverride.trim()) params.vocals = vocalsOverride.trim()
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

  const leadSrc =
    (stageRun.result?.artifacts?.lead_vocals as string | undefined) ?? defaults.artifacts.deharm_lead
  const backingSrc =
    (stageRun.result?.artifacts?.backing_vocals as string | undefined) ?? defaults.artifacts.deharm_backing

  return (
    <div className="grid gap-6 lg:grid-cols-2" data-testid="deharmonize-page">
      <Card>
        <CardHeader>
          <CardTitle>和声剥离参数</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            将混合人声解耦为主唱（Lead）与背景和声（Backing）。Karaoke 模型的 Instrumental stem 在此语境下为和声，非伴奏。
          </p>
          <PathInput
            label="混合人声（留空则使用 separate 产物）"
            value={vocalsOverride}
            onChange={setVocalsOverride}
            extensions={['.flac', '.wav', '.mp3']}
            helpText={
              defaults.vocals_path ? `当前默认：${defaults.vocals_path}` : '尚未解析到混合人声'
            }
          />
          <StageParamForm
            params={schema.params}
            defaultValues={defaults.stage_params.deharmonize ?? {}}
            onSubmit={handleSubmit}
            submitLabel="运行和声剥离"
            isSubmitting={stageRun.status === 'running'}
            extraFooter={
              stageRun.status === 'running' ? (
                <Button
                  type="button"
                  variant="outline"
                  onClick={stageRun.cancel}
                  data-testid="deharmonize-cancel"
                >
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
          <ArtifactAudio label="主唱 (lead_vocals)" src={leadSrc} />
          <ArtifactAudio label="和声 (backing_vocals)" src={backingSrc} />
        </CardContent>
      </Card>
    </div>
  )
}

export function DeharmonizePage() {
  const { projectId } = useProject()

  if (!projectId) {
    return <p className="text-sm text-muted-foreground">请先在左侧选择或创建一个项目。</p>
  }

  return <DeharmonizePageInner key={projectId} projectId={projectId} />
}
