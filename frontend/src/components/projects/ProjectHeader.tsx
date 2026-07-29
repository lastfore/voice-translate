import { Trash2Icon } from 'lucide-react'

import { DeleteProjectDialog } from '@/components/projects/DeleteProjectDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useProject } from '@/context/ProjectContext'
import { useProjects } from '@/hooks/useProjects'
import { STAGE_LABELS, stageStatusIcon } from '@/lib/format'
import type { StageName } from '@/types/pipeline'

const STAGE_ORDER: StageName[] = ['separate', 'slice', 'convert', 'merge']

export function ProjectHeader() {
  const { projectId } = useProject()
  const { data: projects } = useProjects()

  if (!projectId) {
    return (
      <div className="mb-4 rounded-lg border border-dashed p-4 text-sm text-muted-foreground" data-testid="project-header-empty">
        请从左侧选择项目
      </div>
    )
  }

  const project = projects?.find((item) => item.id === projectId)
  const displayName = project?.display_name ?? projectId

  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3 rounded-lg border bg-card p-4" data-testid="project-header">
      <div className="min-w-0 space-y-2">
        <div>
          <h1 className="truncate text-lg font-semibold">{displayName}</h1>
          <p className="truncate text-sm text-muted-foreground">{projectId}</p>
        </div>
        {project && (
          <div className="flex flex-wrap gap-1">
            {STAGE_ORDER.map((stage) => (
              <Badge
                key={stage}
                variant={project.stages[stage] === 'done' ? 'success' : 'outline'}
                className="text-[10px]"
              >
                {stageStatusIcon(project.stages[stage])}
                {STAGE_LABELS[stage]}
              </Badge>
            ))}
          </div>
        )}
      </div>
      <DeleteProjectDialog
        projectIds={[projectId]}
        trigger={
          <Button variant="destructive" size="sm" className="gap-1 shrink-0" data-testid="delete-project-trigger">
            <Trash2Icon className="size-4" />
            删除项目
          </Button>
        }
      />
    </div>
  )
}
