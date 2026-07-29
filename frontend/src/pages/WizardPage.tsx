import { useState } from 'react'
import { toast } from 'sonner'

import { StageParamForm } from '@/components/forms/StageParamForm'
import { StageLogPanel } from '@/components/pipeline/StageLogPanel'
import { WizardStepper } from '@/components/pipeline/WizardStepper'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { useProject } from '@/context/ProjectContext'
import { projectDefaultsKey, useProjectDefaults } from '@/hooks/useProjectDefaults'
import { usePipelineRun } from '@/hooks/usePipelineRun'
import { useStageParams } from '@/hooks/useStageParams'
import { useQueryClient } from '@tanstack/react-query'
import type { ProjectDefaults, StageName, StageParamValues } from '@/types/pipeline'

const STAGES: StageName[] = ['separate', 'slice', 'convert', 'merge']

function buildPipelineParams(defaults: ProjectDefaults): StageParamValues {
  const mode = defaults.active_slice_mode
  const mergeParams = defaults.stage_params.merge ?? {}
  return {
    slice_mode: mode,
    active_slice_mode: mode,
    convert_mode: defaults.convert_mode,
    reference: defaults.reference || undefined,
    profile: (mergeParams.profile as string | undefined) ?? defaults.merge_profile,
    merge_profile: (mergeParams.profile as string | undefined) ?? defaults.merge_profile,
  }
}

export function WizardPage() {
  const { projectId } = useProject()
  const { data: defaults, isLoading } = useProjectDefaults(projectId)
  const { data: schema, isLoading: schemaLoading } = useStageParams({ stage: 'separate' })
  const [activeStage, setActiveStage] = useState<StageName>('separate')
  const pipelineRun = usePipelineRun(projectId)
  const queryClient = useQueryClient()

  if (!projectId) {
    return <p className="text-sm text-muted-foreground">请先在左侧选择或创建一个项目。</p>
  }

  if (isLoading || !defaults) {
    return <Skeleton className="h-64 w-full" />
  }

  const handleRunStep = (values: StageParamValues) => {
    pipelineRun.run({ stages: [activeStage], params: values })
  }

  const handleRunFrom = () => {
    const idx = STAGES.indexOf(activeStage)
    const stages = STAGES.slice(idx)
    pipelineRun.run({ stages, params: buildPipelineParams(defaults) })
  }

  const handleRunAll = () => {
    pipelineRun.run({ params: buildPipelineParams(defaults) })
  }

  if (pipelineRun.status === 'done') {
    toast.success('向导流程完成')
    queryClient.invalidateQueries({ queryKey: projectDefaultsKey(projectId) })
  } else if (pipelineRun.status === 'failed' || pipelineRun.status === 'error') {
    toast.error(pipelineRun.errorMessage ?? '向导运行失败')
  }

  return (
    <div className="space-y-4" data-testid="wizard-page">
      <WizardStepper stages={STAGES} active={activeStage} onChange={setActiveStage} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>步骤参数（{activeStage}）</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {schemaLoading || !schema ? (
              <Skeleton className="h-32 w-full" />
            ) : (
              <StageParamForm
                params={schema.params}
                defaultValues={defaults.stage_params[activeStage] ?? {}}
                onSubmit={handleRunStep}
                submitLabel={`运行 ${activeStage}`}
                isSubmitting={pipelineRun.status === 'running'}
                extraFooter={
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleRunFrom}
                      disabled={pipelineRun.status === 'running'}
                      data-testid="wizard-run-from"
                    >
                      从此步到最后
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleRunAll}
                      disabled={pipelineRun.status === 'running'}
                      data-testid="wizard-run-all"
                    >
                      全流程
                    </Button>
                    {pipelineRun.status === 'running' ? (
                      <Button type="button" variant="outline" onClick={pipelineRun.cancel}>
                        取消
                      </Button>
                    ) : null}
                  </div>
                }
              />
            )}
            <Separator />
            <StageLogPanel status={pipelineRun.status} logs={pipelineRun.logs} errorMessage={pipelineRun.errorMessage} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>产物预览</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-sm text-muted-foreground">当前步骤：{activeStage}</p>
            <p className="text-sm text-muted-foreground">
              状态：{defaults.stage_status[activeStage] ?? 'not_run'}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
