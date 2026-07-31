import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2Icon, PlusIcon, RefreshCwIcon, Trash2Icon } from 'lucide-react'

import { DeleteProjectDialog } from '@/components/projects/DeleteProjectDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useProject } from '@/context/ProjectContext'
import { PROJECTS_QUERY_KEY, useCreateProject, useProjects } from '@/hooks/useProjects'
import { STAGE_LABELS, stageStatusIcon } from '@/lib/format'
import { ApiError } from '@/lib/api'
import type { ProjectSummary, StageName } from '@/types/pipeline'

const STAGE_ORDER: StageName[] = ['separate', 'deharmonize', 'slice', 'convert', 'merge']

interface ProjectRowProps {
  project: ProjectSummary
  active: boolean
  multiSelectMode: boolean
  checked: boolean
  onSelect: () => void
  onCheckedChange: (checked: boolean) => void
}

function ProjectRow({ project, active, multiSelectMode, checked, onSelect, onCheckedChange }: ProjectRowProps) {
  return (
    <div
      data-testid="project-row"
      data-project-id={project.id}
      className={`flex items-start gap-1 rounded-md border px-2 py-2 transition-colors ${
        active ? 'border-primary bg-accent' : 'border-transparent hover:bg-accent/50'
      }`}
    >
      {multiSelectMode && (
        <Checkbox
          checked={checked}
          onCheckedChange={(value) => onCheckedChange(value === true)}
          className="mt-1 shrink-0"
          data-testid={`project-select-${project.id}`}
          aria-label={`选择项目 ${project.id}`}
        />
      )}
      <button type="button" onClick={onSelect} className="min-w-0 flex-1 text-left">
        <p className="truncate text-sm font-medium">
          {project.display_name} <span className="text-muted-foreground">({project.id})</span>
        </p>
        <div className="mt-1 flex flex-wrap gap-1">
          {STAGE_ORDER.map((stage) => (
            <Badge key={stage} variant={project.stages[stage] === 'done' ? 'success' : 'outline'} className="text-[10px]">
              {stageStatusIcon(project.stages[stage])}
              {STAGE_LABELS[stage]}
            </Badge>
          ))}
        </div>
      </button>
      <DeleteProjectDialog
        projectIds={[project.id]}
        trigger={
          <Button
            variant="ghost"
            size="icon"
            className="size-7 shrink-0 text-muted-foreground hover:text-destructive"
            data-testid={`delete-project-row-${project.id}`}
            aria-label={`删除项目 ${project.id}`}
            onClick={(event) => event.stopPropagation()}
          >
            <Trash2Icon className="size-3.5" />
          </Button>
        }
      />
    </div>
  )
}

function CreateProjectDialog() {
  const [open, setOpen] = useState(false)
  const [projectId, setProjectId] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [audio, setAudio] = useState<File | null>(null)
  const [lrc, setLrc] = useState<File | null>(null)
  const createProject = useCreateProject()
  const { setProjectId: selectProject } = useProject()

  const handleCreate = () => {
    if (!projectId.trim() || !audio) {
      toast.error('项目 ID 与混音文件为必填项')
      return
    }
    createProject.mutate(
      { projectId: projectId.trim(), displayName: displayName.trim() || undefined, audio, lrc },
      {
        onSuccess: (created) => {
          toast.success(`项目 ${created.id} 创建成功`)
          selectProject(created.id)
          setOpen(false)
          setProjectId('')
          setDisplayName('')
          setAudio(null)
          setLrc(null)
        },
        onError: (err) => {
          toast.error(err instanceof ApiError ? err.message : '创建项目失败')
        },
      }
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1" data-testid="create-project-trigger">
          <PlusIcon className="size-4" />
          新建项目
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建项目</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>项目 ID</Label>
            <Input value={projectId} onChange={(e) => setProjectId(e.target.value)} placeholder="例如 mysong" data-testid="create-project-id" />
          </div>
          <div className="space-y-1.5">
            <Label>显示名称（可选）</Label>
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>混音文件</Label>
            <Input type="file" accept="audio/*,.flac,.wav,.mp3" onChange={(e) => setAudio(e.target.files?.[0] ?? null)} data-testid="create-project-audio" />
          </div>
          <div className="space-y-1.5">
            <Label>歌词 LRC（可选）</Label>
            <Input type="file" accept=".lrc" onChange={(e) => setLrc(e.target.files?.[0] ?? null)} />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={handleCreate} disabled={createProject.isPending} data-testid="create-project-submit">
            {createProject.isPending ? <Loader2Icon className="size-4 animate-spin" /> : null}
            创建项目
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Project list + create/delete — migrated from webui/components/project_sidebar.py
 * (migration doc §5.1). Selecting a project goes through `useProject().setProjectId`,
 * which handles the old-project cache cleanup (§6.2).
 */
export function AppSidebar() {
  const { projectId, setProjectId } = useProject()
  const { data: projects, isLoading, refetch, isFetching } = useProjects()
  const queryClient = useQueryClient()
  const [multiSelectMode, setMultiSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false)

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: PROJECTS_QUERY_KEY })
    refetch()
  }

  const toggleMultiSelect = () => {
    setMultiSelectMode((prev) => {
      if (prev) setSelectedIds([])
      return !prev
    })
  }

  const handleCheckedChange = (id: string, checked: boolean) => {
    setSelectedIds((prev) => (checked ? [...prev, id] : prev.filter((item) => item !== id)))
  }

  const visibleProjectIds = projects?.map((project) => project.id) ?? []
  const allSelected = visibleProjectIds.length > 0 && selectedIds.length === visibleProjectIds.length

  const handleSelectAll = () => {
    if (allSelected) {
      setSelectedIds([])
      return
    }
    setSelectedIds(visibleProjectIds)
  }

  return (
    <Card className="flex h-full min-h-0 flex-col gap-0 rounded-none border-0 border-r py-4" data-testid="app-sidebar">
      <CardHeader className="shrink-0 px-4">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">项目</CardTitle>
          <div className="flex items-center gap-1">
            <Button
              variant={multiSelectMode ? 'secondary' : 'ghost'}
              size="sm"
              onClick={toggleMultiSelect}
              data-testid="project-multi-select-toggle"
            >
              多选
            </Button>
            <Button variant="ghost" size="icon" onClick={handleRefresh} data-testid="refresh-projects" aria-label="刷新列表">
              <RefreshCwIcon className={isFetching ? 'size-4 animate-spin' : 'size-4'} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-4">
        <div className="shrink-0">
          <CreateProjectDialog />
        </div>
        <Separator className="shrink-0" />
        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-2 pr-2" data-testid="project-list">
            {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
            {projects && projects.length === 0 && <p className="text-sm text-muted-foreground">暂无项目</p>}
            {projects?.map((project) => (
              <ProjectRow
                key={project.id}
                project={project}
                active={project.id === projectId}
                multiSelectMode={multiSelectMode}
                checked={selectedIds.includes(project.id)}
                onSelect={() => setProjectId(project.id)}
                onCheckedChange={(checked) => handleCheckedChange(project.id, checked)}
              />
            ))}
          </div>
        </ScrollArea>
        {multiSelectMode && (
          <div className="shrink-0 space-y-2 border-t pt-3" data-testid="project-batch-actions">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">已选 {selectedIds.length} 项</p>
              <Button
                variant="ghost"
                size="sm"
                className="h-auto px-2 text-xs"
                disabled={visibleProjectIds.length === 0}
                onClick={handleSelectAll}
                data-testid="project-select-all"
              >
                {allSelected ? '取消全选' : '全选'}
              </Button>
            </div>
            <Button
              variant="destructive"
              size="sm"
              className="w-full gap-1"
              disabled={selectedIds.length === 0}
              onClick={() => setBatchDeleteOpen(true)}
              data-testid="delete-selected-projects"
            >
              <Trash2Icon className="size-4" />
              删除所选
            </Button>
            <DeleteProjectDialog
              projectIds={selectedIds}
              open={batchDeleteOpen}
              onOpenChange={setBatchDeleteOpen}
              onDeleted={() => {
                setSelectedIds([])
                setMultiSelectMode(false)
              }}
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
