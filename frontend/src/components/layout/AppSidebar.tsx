import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2Icon, PlusIcon, RefreshCwIcon, Trash2Icon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useProject } from '@/context/ProjectContext'
import {
  PROJECTS_QUERY_KEY,
  useCreateProject,
  useDeletePreview,
  useDeleteProject,
  useProjects,
  type DeleteScope,
} from '@/hooks/useProjects'
import { STAGE_LABELS, stageStatusIcon } from '@/lib/format'
import { ApiError } from '@/lib/api'
import type { ProjectSummary, StageName } from '@/types/pipeline'

const STAGE_ORDER: StageName[] = ['separate', 'slice', 'convert', 'merge']

function ProjectRow({ project, active, onSelect }: { project: ProjectSummary; active: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      data-testid="project-row"
      data-project-id={project.id}
      className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
        active ? 'border-primary bg-accent' : 'border-transparent hover:bg-accent/50'
      }`}
    >
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

function DeleteProjectDialog({ projectId }: { projectId: string }) {
  const [scope, setScope] = useState<DeleteScope>('metadata')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const { data: preview } = useDeletePreview(confirmOpen ? projectId : null, scope)
  const deleteProject = useDeleteProject()
  const { setProjectId } = useProject()

  const handleDelete = () => {
    deleteProject.mutate(
      { projectId, scope, confirmed: true },
      {
        onSuccess: () => {
          toast.success(`项目 ${projectId} 已删除`)
          setProjectId(null)
          setConfirmOpen(false)
        },
        onError: (err) => toast.error(err instanceof ApiError ? err.message : '删除失败'),
      }
    )
  }

  return (
    <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
      <AlertDialogTrigger asChild>
        <Button variant="destructive" size="sm" className="gap-1" data-testid="delete-project-trigger">
          <Trash2Icon className="size-4" />
          删除项目
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>删除项目 {projectId}</AlertDialogTitle>
          <AlertDialogDescription>此操作不可恢复，请谨慎选择删除范围。</AlertDialogDescription>
        </AlertDialogHeader>
        <RadioGroup value={scope} onValueChange={(v) => setScope(v as DeleteScope)} className="my-2">
          <div className="flex items-center gap-2">
            <RadioGroupItem value="metadata" id="scope-metadata" />
            <Label htmlFor="scope-metadata">仅从列表移除（保留所有文件）</Label>
          </div>
          <div className="flex items-center gap-2">
            <RadioGroupItem value="artifacts" id="scope-artifacts" />
            <Label htmlFor="scope-artifacts">删除产物（保留 input 原文件）</Label>
          </div>
          <div className="flex items-center gap-2">
            <RadioGroupItem value="all" id="scope-all" />
            <Label htmlFor="scope-all">彻底删除（含 input 与 separated）</Label>
          </div>
        </RadioGroup>
        {preview && preview.length > 0 && (
          <ScrollArea className="h-32 rounded-md border p-2 text-xs">
            {preview.map((row, idx) => (
              <p key={idx} className="truncate">
                [{row.kind}] {row.path}
              </p>
            ))}
          </ScrollArea>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction onClick={handleDelete} data-testid="delete-project-confirm">
            确认删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
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

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: PROJECTS_QUERY_KEY })
    refetch()
  }

  return (
    <Card className="flex h-full flex-col gap-0 rounded-none border-0 border-r py-4" data-testid="app-sidebar">
      <CardHeader className="px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">项目</CardTitle>
          <Button variant="ghost" size="icon" onClick={handleRefresh} data-testid="refresh-projects" aria-label="刷新列表">
            <RefreshCwIcon className={isFetching ? 'size-4 animate-spin' : 'size-4'} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3 overflow-hidden px-4">
        <CreateProjectDialog />
        <Separator />
        <ScrollArea className="flex-1">
          <div className="space-y-2 pr-2" data-testid="project-list">
            {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
            {projects && projects.length === 0 && <p className="text-sm text-muted-foreground">暂无项目</p>}
            {projects?.map((project) => (
              <ProjectRow key={project.id} project={project} active={project.id === projectId} onSelect={() => setProjectId(project.id)} />
            ))}
          </div>
        </ScrollArea>
        {projectId && (
          <>
            <Separator />
            <DeleteProjectDialog projectId={projectId} />
          </>
        )}
      </CardContent>
    </Card>
  )
}
